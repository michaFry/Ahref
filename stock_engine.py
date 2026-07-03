#!/usr/bin/env python3
"""Single-stock analysis engine.

Give it a ticker; it fetches the stock's own fundamentals from Yahoo Finance,
scores them on the same 0-100 "stretch" scale as the macro engine (0 =
attractive / high quality, 100 = expensive / fragile), and combines the result
with the market-wide macro backdrop produced by ``valuation_engine``.

Why two engines?
----------------
The seven macro indicators (CAPE, Buffett, Tobin's Q, ...) describe the *whole
market* and are identical whatever ticker you look at. A single stock needs its
*own* fundamentals — P/E, PEG, margins, growth, debt. This module supplies that
company layer and blends it with the macro context so you get both:

    Score titre   -> is THIS company cheap/expensive & solid/fragile?
    Score marché  -> is the ENVIRONMENT rich or cheap? (caps forward returns)
    Score global  -> blended outlook (60 % titre / 40 % marché)

Data source: Yahoo Finance public JSON endpoints (no API key; a cookie+crumb
handshake is performed automatically). Network egress uses the environment
proxy and CA bundle transparently via urllib.

Usage
-----
    python stock_engine.py AAPL [MSFT ...]

Writes data/stock_<TICKER>.json for each and prints a report. Pair with
render_stock.py to build an HTML dashboard.
"""
from __future__ import annotations

import http.cookiejar
import json
import pathlib
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from valuation_engine import DEFAULT_INPUT, analyze as analyze_macro, interpolate

ROOT = pathlib.Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# A browser-like header set is required: Yahoo's anti-bot returns 401/406 to
# minimal clients, and the cookie/crumb handshake only completes with these.
_HEADERS = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "en-US,en;q=0.9"),
]
_HOSTS = ["query2.finance.yahoo.com", "query1.finance.yahoo.com"]


# --------------------------------------------------------------------------
# Yahoo Finance fetch (cookie + crumb handshake, stdlib only).
# --------------------------------------------------------------------------
def _build_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = list(_HEADERS)
    return opener


def _get(opener: urllib.request.OpenerDirector, url: str, timeout: int = 20) -> bytes:
    with opener.open(url, timeout=timeout) as r:
        return r.read()


def _fetch_summary(ticker: str) -> dict[str, Any] | None:
    """One cookie+crumb handshake attempt. Returns the summary dict or None."""
    opener = _build_opener()
    # Prime session cookies (A1/A3) by loading Yahoo pages first.
    for prime in ("https://fc.yahoo.com", "https://finance.yahoo.com",
                  f"https://finance.yahoo.com/quote/{urllib.parse.quote(ticker)}"):
        try:
            _get(opener, prime, timeout=15)
        except Exception:
            continue  # priming is best-effort; a 404/401 here is harmless
    crumb = ""
    for host in _HOSTS:
        try:
            crumb = _get(opener, f"https://{host}/v1/test/getcrumb", timeout=15).decode().strip()
            if crumb and "<" not in crumb:
                break
        except Exception:
            continue
    if not crumb or "<" in crumb:
        return None

    modules = "summaryDetail,defaultKeyStatistics,financialData,assetProfile,price"
    for host in _HOSTS:
        url = (f"https://{host}/v10/finance/quoteSummary/{ticker}"
               f"?modules={modules}&crumb={urllib.parse.quote(crumb)}")
        try:
            payload = json.loads(_get(opener, url))
            res = payload.get("quoteSummary", {}).get("result")
            if res:
                return res[0]
        except Exception:
            continue
    return None


def fetch_fundamentals(ticker: str) -> dict[str, Any]:
    """Return raw fundamentals + price context for ``ticker`` from Yahoo."""
    ticker = ticker.strip().upper()
    summary = None
    for _ in range(3):  # Yahoo's anti-bot is flaky; a couple of retries suffice.
        summary = _fetch_summary(ticker)
        if summary is not None:
            break
    if summary is None:
        raise RuntimeError(
            f"Impossible de récupérer les fondamentaux de {ticker} "
            f"(Yahoo a refusé la requête ou le ticker est inconnu).")

    def raw(mod: str, key: str) -> float | str | None:
        v = summary.get(mod, {}).get(key)
        if isinstance(v, dict):
            return v.get("raw")
        return v

    price_ctx = {
        "price": raw("price", "regularMarketPrice"),
        "currency": raw("price", "currency"),
        "week52_high": raw("summaryDetail", "fiftyTwoWeekHigh"),
        "week52_low": raw("summaryDetail", "fiftyTwoWeekLow"),
        "market_cap": raw("summaryDetail", "marketCap"),
        "recommendation": raw("financialData", "recommendationKey"),
    }
    fundamentals = {
        "trailing_pe": raw("summaryDetail", "trailingPE"),
        "forward_pe": raw("summaryDetail", "forwardPE"),
        "peg_ratio": raw("defaultKeyStatistics", "pegRatio")
                     or raw("defaultKeyStatistics", "trailingPegRatio"),
        "price_to_sales": raw("summaryDetail", "priceToSalesTrailing12Months"),
        "price_to_book": raw("defaultKeyStatistics", "priceToBook"),
        "profit_margins": raw("financialData", "profitMargins"),
        "operating_margins": raw("financialData", "operatingMargins"),
        "return_on_equity": raw("financialData", "returnOnEquity"),
        "revenue_growth": raw("financialData", "revenueGrowth"),
        "earnings_growth": raw("financialData", "earningsGrowth"),
        "debt_to_equity": raw("financialData", "debtToEquity"),
        "current_ratio": raw("financialData", "currentRatio"),
    }
    return {
        "ticker": ticker,
        "name": raw("price", "longName") or raw("price", "shortName") or ticker,
        "sector": raw("assetProfile", "sector"),
        "industry": raw("assetProfile", "industry"),
        "price": price_ctx,
        "fundamentals": fundamentals,
    }


# --------------------------------------------------------------------------
# Stock-level scoring. 0 = attractive/solid, 100 = expensive/fragile.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    weight: float
    family: str
    anchors: list[tuple[float, float]]
    # Some Yahoo fields are fractions (0.27) we display as %; scale for display.
    display_pct: bool = False
    note: str = ""


# For "higher is better" metrics (margins, growth, ROE, current ratio) the
# anchor y-values DECREASE as x increases, so a strong company scores low.
METRICS: list[Metric] = [
    # --- Valorisation (raw haut = plus cher = score haut) ---
    Metric("peg_ratio", "PEG ratio", "", 1.3, "valuation",
           [(0.5, 5), (1.0, 30), (1.5, 52), (2.0, 68), (3.0, 85), (5.0, 100)],
           note="P/E ajusté de la croissance. <1 attractif, >2 tendu."),
    Metric("trailing_pe", "P/E (12 m)", "x", 1.1, "valuation",
           [(8, 5), (15, 32), (22, 52), (30, 70), (45, 88), (70, 100)],
           note="Cours / bénéfices. Sensible au secteur."),
    Metric("forward_pe", "P/E anticipé", "x", 1.0, "valuation",
           [(7, 3), (13, 28), (20, 50), (28, 68), (40, 86), (65, 100)],
           note="Cours / bénéfices attendus 12 m."),
    Metric("price_to_sales", "P/S", "x", 0.8, "valuation",
           [(1, 8), (3, 38), (6, 60), (10, 78), (15, 90), (25, 100)],
           note="Cours / chiffre d'affaires."),
    Metric("price_to_book", "P/B", "x", 0.6, "valuation",
           [(1, 10), (3, 40), (6, 62), (12, 80), (25, 94), (45, 100)],
           note="Cours / valeur comptable. Élevé normal pour l'asset-light/tech."),
    # --- Rentabilité (raw haut = mieux = score bas) ---
    Metric("profit_margins", "Marge nette", "%", 1.0, "profitability",
           [(-0.05, 100), (0.02, 82), (0.06, 64), (0.12, 45), (0.20, 25), (0.30, 8), (0.45, 0)],
           display_pct=True, note="Bénéfice net / chiffre d'affaires."),
    Metric("return_on_equity", "ROE", "%", 0.9, "profitability",
           [(-0.10, 100), (0, 88), (0.04, 72), (0.10, 50), (0.18, 26), (0.30, 8), (0.60, 0)],
           display_pct=True, note="Rentabilité des capitaux propres (peut être "
           "gonflée par les rachats d'actions)."),
    Metric("operating_margins", "Marge opérationnelle", "%", 0.6, "profitability",
           [(-0.05, 100), (0.02, 82), (0.06, 64), (0.12, 45), (0.20, 25), (0.30, 8), (0.45, 0)],
           display_pct=True, note="Résultat d'exploitation / chiffre d'affaires."),
    # --- Croissance (raw haut = mieux = score bas) ---
    Metric("earnings_growth", "Croissance BPA", "%", 1.0, "growth",
           [(-0.30, 100), (-0.10, 86), (0, 72), (0.05, 55), (0.15, 28), (0.30, 8), (0.50, 0)],
           display_pct=True, note="Croissance des bénéfices (yoy)."),
    Metric("revenue_growth", "Croissance CA", "%", 0.9, "growth",
           [(-0.15, 100), (-0.05, 86), (0, 72), (0.05, 54), (0.12, 30), (0.25, 8), (0.40, 0)],
           display_pct=True, note="Croissance du chiffre d'affaires (yoy)."),
    # --- Solidité financière ---
    Metric("debt_to_equity", "Dette / capitaux", "%", 0.8, "solidity",
           [(0, 8), (50, 28), (100, 48), (200, 72), (400, 90), (700, 100)],
           note="Endettement relatif. Yahoo l'exprime en %."),
    Metric("current_ratio", "Ratio de liquidité", "x", 0.5, "solidity",
           [(0.4, 100), (0.7, 85), (1.0, 62), (1.5, 42), (2.0, 25), (3.0, 10), (5.0, 5)],
           note="Actifs courants / passifs courants. <1 = tension de trésorerie."),
]

STOCK_FAMILIES = {
    "valuation": "Valorisation",
    "profitability": "Rentabilité",
    "growth": "Croissance",
    "solidity": "Solidité financière",
}


@dataclass(frozen=True)
class StockBand:
    lo: float
    hi: float
    verdict: str
    stance: str
    color: str


STOCK_BANDS: list[StockBand] = [
    StockBand(0, 30, "Attractif — qualité à bon prix",
              "Profil valorisation/qualité favorable ; candidat à l'accumulation.",
              "#1a7f37"),
    StockBand(30, 45, "Raisonnable",
              "Valorisation correcte au regard des fondamentaux ; entrée acceptable.",
              "#4a9e4a"),
    StockBand(45, 60, "Neutre / à surveiller",
              "Ni bon marché ni excessif ; exiger un catalyseur ou un meilleur point d'entrée.",
              "#b0902a"),
    StockBand(60, 75, "Cher ou fragile",
              "Prix élevé et/ou fondamentaux tendus ; marge de sécurité limitée.",
              "#e0562b"),
    StockBand(75, 100.0001, "Très cher / risqué",
              "Valorisation extrême et/ou bilan fragile ; risque de correction élevé.",
              "#c1121f"),
]


def stock_band_for(score: float) -> StockBand:
    for b in STOCK_BANDS:
        if b.lo <= score < b.hi:
            return b
    return STOCK_BANDS[-1]


def _assessment(score: float) -> str:
    if score < 30:
        return "attractif"
    if score < 45:
        return "raisonnable"
    if score < 60:
        return "neutre"
    if score < 75:
        return "tendu"
    return "extrême"


def score_stock(fundamentals: dict[str, Any]) -> dict[str, Any]:
    scored = []
    for m in METRICS:
        v = fundamentals.get(m.key)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        s = round(interpolate(v, m.anchors), 1)
        disp = f"{v * 100:.1f}%" if m.display_pct else f"{v:g}{m.unit}"
        scored.append({
            "key": m.key, "label": m.label, "value": v, "display": disp,
            "score": s, "weight": m.weight, "family": m.family,
            "assessment": _assessment(s), "note": m.note,
        })
    if not scored:
        raise ValueError("Aucune donnée fondamentale exploitable.")

    total_w = sum(r["weight"] for r in scored)
    composite = round(sum(r["score"] * r["weight"] for r in scored) / total_w, 1)
    fam_scores = {}
    for fam in STOCK_FAMILIES:
        fr = [r for r in scored if r["family"] == fam]
        if fr:
            fw = sum(r["weight"] for r in fr)
            fam_scores[fam] = round(sum(r["score"] * r["weight"] for r in fr) / fw, 1)

    band = stock_band_for(composite)
    return {
        "stock_score": composite,
        "verdict": band.verdict,
        "stance": band.stance,
        "color": band.color,
        "family_scores": fam_scores,
        "metrics": scored,
        "n_metrics": len(scored),
    }


# --------------------------------------------------------------------------
# Combined (stock + macro) outlook.
# --------------------------------------------------------------------------
def _combined_note(stock: float, macro: float) -> str:
    cheap_stock = stock < 45
    rich_market = macro >= 70
    if cheap_stock and rich_market:
        return ("Titre raisonnable dans un marché survalorisé : intéressant en "
                "relatif, mais le contexte macro plafonne les rendements et "
                "amplifie le risque de baisse générale.")
    if cheap_stock and not rich_market:
        return ("Titre attractif dans un marché non extrême : configuration la "
                "plus favorable.")
    if not cheap_stock and rich_market:
        return ("Titre cher dans un marché cher : double survalorisation, risque "
                "de correction élevé — privilégier la patience.")
    return ("Titre tendu mais marché non extrême : le risque vient surtout du "
            "titre lui-même ; exiger une décote ou un catalyseur.")


def analyze_ticker(ticker: str, macro_readings: dict | None = None) -> dict[str, Any]:
    data = fetch_fundamentals(ticker)
    stock = score_stock(data["fundamentals"])

    macro = None
    if macro_readings is None and DEFAULT_INPUT.exists():
        raw = json.loads(DEFAULT_INPUT.read_text())
        macro_readings = raw.get("indicators", raw) if isinstance(raw, dict) else raw
    if macro_readings:
        try:
            macro = analyze_macro(macro_readings)
        except Exception:
            macro = None

    combined = None
    if macro is not None:
        blended = round(0.6 * stock["stock_score"] + 0.4 * macro["composite_score"], 1)
        combined = {
            "global_score": blended,
            "weights": {"titre": 0.6, "marché": 0.4},
            "note": _combined_note(stock["stock_score"], macro["composite_score"]),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ticker": data["ticker"],
        "name": data["name"],
        "sector": data["sector"],
        "industry": data["industry"],
        "price": data["price"],
        "stock": stock,
        "macro": {
            "composite_score": macro["composite_score"],
            "verdict": macro["verdict"],
            "expected_10y_real_return_pct": macro["expected_10y_real_return_pct"],
        } if macro else None,
        "combined": combined,
    }


# --------------------------------------------------------------------------
# CLI report.
# --------------------------------------------------------------------------
def _bar(score: float, width: int = 22) -> str:
    filled = int(round(score / 100 * width))
    return "█" * filled + "·" * (width - filled)


def print_report(a: dict[str, Any]) -> None:
    p = a["price"]
    print("=" * 60)
    print(f"  {a['ticker']} — {a['name']}")
    if a["sector"]:
        print(f"  {a['sector']} · {a.get('industry') or ''}".rstrip(" ·"))
    if p.get("price") is not None:
        cur = p.get("currency") or ""
        line = f"  Cours : {p['price']:g} {cur}".rstrip()
        if p.get("week52_low") and p.get("week52_high"):
            line += f"   (52 s. : {p['week52_low']:g}–{p['week52_high']:g})"
        print(line)
    print("=" * 60)
    st = a["stock"]
    for r in st["metrics"]:
        print(f"  {r['label']:<24} {r['display']:>9}")
        print(f"    {_bar(r['score'])} {r['score']:>5}/100 ({r['assessment']})")
    print("-" * 60)
    for fam, name in STOCK_FAMILIES.items():
        if fam in st["family_scores"]:
            print(f"  {name:<22} {st['family_scores'][fam]:>5}/100")
    print("-" * 60)
    print(f"  SCORE TITRE   {_bar(st['stock_score'])} {st['stock_score']}/100")
    print(f"  VERDICT : {st['verdict']}")
    print(f"  POSTURE : {st['stance']}")
    if a.get("macro"):
        m = a["macro"]
        print("-" * 60)
        print(f"  Contexte marché : {m['composite_score']}/100 ({m['verdict']})")
        if m["expected_10y_real_return_pct"] is not None:
            print(f"  Rendement réel marché 10 ans estimé : "
                  f"{m['expected_10y_real_return_pct']:+.1f} %/an")
    if a.get("combined"):
        c = a["combined"]
        print("-" * 60)
        print(f"  SCORE GLOBAL  {_bar(c['global_score'])} {c['global_score']}/100 "
              f"(titre 60 % / marché 40 %)")
        print(f"  {c['note']}")
    print("=" * 60)
    if p.get("recommendation"):
        print(f"  (Consensus analystes Yahoo : {p['recommendation']})")


def main(argv: list[str]) -> int:
    tickers = [t for t in argv[1:] if not t.startswith("-")]
    if not tickers:
        print("Usage: python stock_engine.py <TICKER> [TICKER ...]", file=sys.stderr)
        print("Exemple: python stock_engine.py AAPL MSFT", file=sys.stderr)
        return 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0
    for i, t in enumerate(tickers):
        try:
            a = analyze_ticker(t)
        except Exception as e:  # noqa: BLE001
            print(f"[{t}] Erreur : {e}", file=sys.stderr)
            rc = 1
            continue
        out = DATA_DIR / f"stock_{a['ticker']}.json"
        out.write_text(json.dumps(a, indent=2, ensure_ascii=False))
        if i:
            print()
        print_report(a)
        print(f"\nAnalyse écrite -> {out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
