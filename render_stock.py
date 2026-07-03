#!/usr/bin/env python3
"""Render data/stock_<TICKER>.json -> stock_<TICKER>.html (self-contained).

Run `python stock_engine.py <TICKER>` first, then this script.

Usage:
    python render_stock.py AAPL
"""
from __future__ import annotations

import html
import json
import pathlib
import sys

from stock_engine import STOCK_FAMILIES

ROOT = pathlib.Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def score_color(score: float) -> str:
    if score < 30:
        return "#1a7f37"
    if score < 45:
        return "#4a9e4a"
    if score < 60:
        return "#b0902a"
    if score < 75:
        return "#e0562b"
    return "#c1121f"


def render(ticker: str) -> pathlib.Path:
    src = DATA_DIR / f"stock_{ticker.upper()}.json"
    if not src.exists():
        raise SystemExit(f"{src} manquant — lancez d'abord "
                         f"`python stock_engine.py {ticker.upper()}`.")
    a = json.loads(src.read_text())
    st = a["stock"]

    rows = []
    for r in st["metrics"]:
        col = score_color(r["score"])
        rows.append(f"""
  <div class="ind">
    <div class="ind-head">
      <span class="ind-label">{html.escape(r["label"])}</span>
      <span class="ind-val">{html.escape(str(r["display"]))}</span>
    </div>
    <div class="track"><div class="fill" style="width:{r['score']}%;background:{col}"></div></div>
    <div class="ind-foot">
      <span class="score" style="color:{col}">{r['score']:g}/100 · {html.escape(r['assessment'])}</span>
      <span class="fam">{html.escape(STOCK_FAMILIES.get(r['family'], r['family']))}</span>
    </div>
    <p class="note">{html.escape(r["note"])}</p>
  </div>""")

    chips = []
    for fam, name in STOCK_FAMILIES.items():
        if fam in st["family_scores"]:
            s = st["family_scores"][fam]
            chips.append(f'<span class="chip" style="border-color:{score_color(s)}">'
                         f'{html.escape(name)} <b>{s:g}</b></span>')

    stock_score = st["stock_score"]
    col = a["stock"].get("color", score_color(stock_score))
    p = a["price"]
    price_line = ""
    if p.get("price") is not None:
        rng = ""
        if p.get("week52_low") and p.get("week52_high"):
            rng = f' · 52 s. {p["week52_low"]:g}–{p["week52_high"]:g}'
        price_line = (f'{p["price"]:g} {html.escape(p.get("currency") or "")}'
                      f'{html.escape(rng)}')

    macro_block = ""
    if a.get("macro"):
        m = a["macro"]
        mc = score_color(m["composite_score"])
        fwd = m["expected_10y_real_return_pct"]
        fwd_s = f' · rendement réel 10 ans estimé {fwd:+.1f} %/an' if fwd is not None else ""
        macro_block = (f'<div class="ctx">Contexte marché : '
                       f'<b style="color:{mc}">{m["composite_score"]:g}/100</b> '
                       f'({html.escape(m["verdict"])}){html.escape(fwd_s)}</div>')

    combined_block = ""
    if a.get("combined"):
        c = a["combined"]
        gc = score_color(c["global_score"])
        combined_block = f"""
<div class="gauge" style="margin-top:1em">
  <div class="big" style="color:{gc}">{c['global_score']:g}<small>/100</small></div>
  <div class="verdict" style="color:{gc}">Score global — titre 60 % / marché 40 %</div>
  <div class="master"><div style="width:{c['global_score']}%;background:{gc}"></div></div>
  <p class="stance">{html.escape(c["note"])}</p>
</div>"""

    reco = ""
    if p.get("recommendation"):
        reco = (f'<span class="reco">Consensus analystes Yahoo : '
                f'<b>{html.escape(str(p["recommendation"]))}</b></span>')

    out = ROOT / f"stock_{a['ticker']}.html"
    out.write_text(f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(a['ticker'])} — analyse fondamentale</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         max-width: 860px; margin: 2em auto; padding: 0 1em; line-height: 1.5; }}
  header {{ border-bottom: 1px solid #ccc; padding-bottom: 0.6em; margin-bottom: 1.2em; }}
  h1 {{ margin: 0; font-size: 1.5em; }}
  .sub {{ color: #888; font-size: 0.9em; }}
  .reco {{ color: #666; font-size: 0.85em; }}
  .gauge {{ text-align: center; margin: 1.2em 0; padding: 1.1em;
           border-radius: 10px; background: rgba(127,127,127,0.08); }}
  .gauge .big {{ font-size: 3em; font-weight: 800; line-height: 1; color: {col}; }}
  .gauge .big small {{ font-size: 0.3em; color: #999; font-weight: 500; }}
  .verdict {{ font-size: 1.1em; font-weight: 700; margin: 0.3em 0 0.1em; color: {col}; }}
  .stance {{ color: #666; font-size: 0.92em; max-width: 52ch; margin: 0.2em auto 0; }}
  .master {{ height: 12px; border-radius: 6px; background: rgba(127,127,127,0.25);
            margin: 0.9em auto 0; max-width: 520px; overflow: hidden; }}
  .master > div {{ height: 100%; width: {stock_score}%; background: {col}; }}
  .ctx {{ text-align: center; font-size: 0.9em; color: #555; margin: 0 0 1em; }}
  .chips {{ text-align: center; margin: 0 0 1.2em; }}
  .chip {{ display: inline-block; border: 2px solid #ccc; border-radius: 999px;
          padding: 0.15em 0.7em; margin: 0.2em; font-size: 0.85em; }}
  .ind {{ padding: 0.8em 1em; margin: 0.7em 0; border-radius: 8px;
         background: rgba(127,127,127,0.06); }}
  .ind-head {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .ind-label {{ font-weight: 600; }}
  .ind-val {{ font-variant-numeric: tabular-nums; font-weight: 700; }}
  .track {{ height: 8px; border-radius: 4px; background: rgba(127,127,127,0.2);
           margin: 0.5em 0 0.35em; overflow: hidden; }}
  .fill {{ height: 100%; }}
  .ind-foot {{ display: flex; justify-content: space-between; font-size: 0.8em; }}
  .score {{ font-weight: 600; }}
  .fam {{ color: #999; }}
  .note {{ font-size: 0.82em; color: #777; margin: 0.4em 0 0; }}
  footer {{ margin-top: 2em; font-size: 0.75em; color: #999; border-top: 1px solid #ddd;
           padding-top: 0.8em; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(a['ticker'])} — {html.escape(a['name'] or '')}</h1>
  <div class="sub">{html.escape(' · '.join(x for x in [a.get('sector'), a.get('industry'), price_line] if x))}</div>
  {reco}
</header>

<div class="gauge">
  <div class="big">{stock_score:g}<small>/100</small></div>
  <div class="verdict">{html.escape(st["verdict"])}</div>
  <p class="stance">{html.escape(st["stance"])}</p>
  <div class="master"><div></div></div>
</div>
{macro_block}
<div class="chips">{''.join(chips)}</div>

{''.join(rows)}
{combined_block}

<footer>
  Score 0 = attractif / solide, 100 = cher / fragile. Données fondamentales
  Yahoo Finance ; le score marché provient du moteur macro (data/indicators.json).
  Outil d'orientation, pas un conseil en investissement.
</footer>
</body>
</html>
""")
    return out


def main(argv: list[str]) -> int:
    tickers = [t for t in argv[1:] if not t.startswith("-")]
    if not tickers:
        print("Usage: python render_stock.py <TICKER> [TICKER ...]", file=sys.stderr)
        return 1
    for t in tickers:
        out = render(t)
        print(f"rendered -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
