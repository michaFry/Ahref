#!/usr/bin/env python3
"""Fetch ~1 year of monthly history for the 8 macro indicators.

Writes data/history.json (used by render_valuation.py to draw a sparkline
under each indicator) and syncs the latest live readings into
data/indicators.json so the engine and the charts agree.

Data sources
------------
Real, keyless feeds:
  - Shiller CAPE .............. multpl.com monthly table
  - VIX ...................... FRED VIXCLS
  - High-yield spread ........ FRED BAMLH0A0HYM2
  - Yield curve 10y-2y ....... FRED T10Y2Y
  - S&P 500 / M2 ............. FRED SP500 / M2SL (computed)

Derived (no clean free feed — tracked via the S&P 500 path, scaled so the
latest point equals the current reading in indicators.json):
  - Buffett indicator, Tobin's Q

Seeded (FINRA margin debt has no clean free feed — edit by hand):
  - Margin Debt / M2

Every series carries its ``source`` so the dashboard can label it honestly.

Usage:  python fetch_history.py
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
INDICATORS = DATA / "indicators.json"
HISTORY = DATA / "history.json"
MONTHS = 13  # ~1 year of monthly points

def _get(url: str, ua: str | None = None, timeout: int = 30) -> bytes:
    """Fetch a URL via curl (reliable through the environment proxy/CA bundle).

    The proxy is picky about User-Agent per host: FRED only responds to curl's
    default UA (a ``Mozilla`` UA triggers an HTTP/2 stream error), while
    multpl.com needs a ``Mozilla`` UA. Pass ``ua`` accordingly.
    """
    cmd = ["curl", "-fsSL", "--max-time", str(timeout)]
    if ua:
        cmd += ["-A", ua]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, check=True)
    return out.stdout


def fred_monthly(series_id: str, months: int = MONTHS) -> "OrderedDict[str, float]":
    """Return {YYYY-MM: last-valid-value} for a FRED series over recent months."""
    # Bound the range so we download ~14 months, not the full multi-decade CSV.
    cosd = (datetime.now(timezone.utc) - timedelta(days=32 * months)).strftime("%Y-%m-%d")
    csv = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv"
               f"?id={series_id}&cosd={cosd}").decode()
    by_month: "OrderedDict[str, float]" = OrderedDict()
    for line in csv.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        date, val = parts
        if val in (".", "", "NaN"):
            continue
        try:
            by_month[date[:7]] = float(val)  # last obs of each month wins
        except ValueError:
            continue
    # Keep the last `months` months.
    items = list(by_month.items())[-months:]
    return OrderedDict(items)


def multpl_cape(months: int = MONTHS) -> "OrderedDict[str, float]":
    """Scrape monthly Shiller CAPE from multpl.com (most recent first)."""
    html = _get("https://www.multpl.com/shiller-pe/table/by-month",
                ua="Mozilla/5.0").decode("utf-8", "ignore")
    cells = re.findall(r"<td[^>]*>\s*([^<]+?)\s*</td>", html)
    out: "OrderedDict[str, float]" = OrderedDict()
    i = 0
    while i < len(cells):
        m = re.match(r"([A-Za-z]{3})\s+\d{1,2},\s+(\d{4})", cells[i])
        if m:
            # The value cell contains an entity/whitespace then the number,
            # e.g. "&#x2002;\n41.60" — extract the first float found.
            val = None
            for j in range(i + 1, min(i + 4, len(cells))):
                # Require a decimal point so we don't match "2002" inside the
                # &#x2002; spacer entity; CAPE values always have decimals.
                nm = re.search(r"\d+\.\d+", cells[j].replace(",", ""))
                if nm:
                    val = float(nm.group())
                    break
            if val is not None:
                mon = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%b %Y").strftime("%Y-%m")
                out.setdefault(mon, val)
        i += 1
    # multpl lists newest-first; reverse to chronological and keep last N.
    chrono = OrderedDict(reversed(list(out.items())))
    items = list(chrono.items())[-months:]
    return OrderedDict(items)


def _points(od: "OrderedDict[str, float]", ndigits: int = 4) -> list[list]:
    return [[k, round(v, ndigits)] for k, v in od.items()]


def build() -> dict:
    raw = json.loads(INDICATORS.read_text())
    current = {k: v for k, v in raw.items() if not k.startswith("_")}

    series: dict[str, dict] = {}
    live_latest: dict[str, float] = {}

    def add(key, od, source, unit=""):
        if od:
            series[key] = {"source": source, "unit": unit, "points": _points(od)}
            live_latest[key] = list(od.values())[-1]

    # --- Real feeds -------------------------------------------------------
    try:
        add("shiller_cape", multpl_cape(), "multpl.com", "x")
    except Exception as e:  # noqa: BLE001
        print(f"WARN cape: {e}")
    try:
        add("vix", fred_monthly("VIXCLS"), "FRED VIXCLS")
    except Exception as e:  # noqa: BLE001
        print(f"WARN vix: {e}")
    try:
        add("hy_credit_spread", fred_monthly("BAMLH0A0HYM2"), "FRED BAMLH0A0HYM2", "pp")
    except Exception as e:  # noqa: BLE001
        print(f"WARN hy: {e}")
    try:
        add("yield_curve_10y2y", fred_monthly("T10Y2Y"), "FRED T10Y2Y", "pp")
    except Exception as e:  # noqa: BLE001
        print(f"WARN curve: {e}")

    # --- S&P 500 / M2 (computed) + S&P path for derived series ------------
    sp500 = m2 = None
    try:
        sp500 = fred_monthly("SP500")
        m2 = fred_monthly("M2SL")
        # Align on the S&P months; forward-fill M2 (monthly, published later).
        m2_items = list(m2.items())
        ratio: "OrderedDict[str, float]" = OrderedDict()
        for mon, sp in sp500.items():
            m2v = m2.get(mon)
            if m2v is None:  # use most recent M2 <= this month
                prior = [v for k, v in m2_items if k <= mon]
                m2v = prior[-1] if prior else (m2_items[-1][1] if m2_items else None)
            if m2v:
                ratio[mon] = sp / m2v
        add("sp500_m2", ratio, "FRED SP500 / M2SL")
    except Exception as e:  # noqa: BLE001
        print(f"WARN sp500_m2: {e}")

    # --- Derived: Buffett & Tobin's Q track the S&P 500 path --------------
    # Scaled so the latest month equals the current reading in indicators.json.
    if sp500:
        sp_items = list(sp500.items())
        sp_latest = sp_items[-1][1]
        for key in ("buffett_indicator", "tobins_q"):
            cur = current.get(key)
            if cur is None:
                continue
            od = OrderedDict((mon, cur * sp / sp_latest) for mon, sp in sp_items)
            series[key] = {"source": "dérivé (trajectoire S&P 500)",
                           "unit": "%" if key == "buffett_indicator" else "",
                           "points": _points(od)}

    # --- Seeded: Margin Debt / M2 (no clean free feed) --------------------
    if "margin_debt_m2" not in series:
        cur = current.get("margin_debt_m2", 5.5)
        # A plausible rising path over the last ~year ending at `cur`.
        shape = [4.55, 4.70, 4.85, 4.95, 5.05, 5.00, 5.15, 5.30, 5.40, 5.45, 5.50, 5.50]
        scaled = [round(x * cur / shape[-1], 3) for x in shape]
        months_axis = [k for k in (series.get("vix", {}).get("points")
                       or series.get("sp500_m2", {}).get("points") or [])]
        labels = [p[0] for p in months_axis][-len(scaled):] or \
                 [f"m-{i}" for i in range(len(scaled))]
        pts = [[labels[i], scaled[i]] for i in range(min(len(labels), len(scaled)))]
        series["margin_debt_m2"] = {"source": "amorcé (à mettre à jour)",
                                    "unit": "%", "points": pts}

    # --- Sync live latest values back into indicators.json ----------------
    changed = False
    for key, val in live_latest.items():
        rounded = round(val, 4)
        if raw.get(key) != rounded:
            raw[key] = rounded
            changed = True
    if changed:
        INDICATORS.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        print("indicators.json synchronisé avec les derniers relevés.")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": series,
    }


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    hist = build()
    HISTORY.write_text(json.dumps(hist, indent=2, ensure_ascii=False))
    n = len(hist["series"])
    print(f"Historique écrit -> {HISTORY} ({n} séries)")
    for k, s in hist["series"].items():
        pts = s["points"]
        lo = min(p[1] for p in pts)
        hi = max(p[1] for p in pts)
        print(f"  {k:<20} {len(pts):>2} pts  [{lo:g} … {hi:g}]  ({s['source']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
