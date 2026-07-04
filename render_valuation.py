#!/usr/bin/env python3
"""Render data/valuation.json -> valuation.html (single self-contained file).

Run `python valuation_engine.py` first to produce data/valuation.json, then
this script to build the dashboard.
"""
from __future__ import annotations

import html
import json
import pathlib

from valuation_engine import FAMILIES

ROOT = pathlib.Path(__file__).resolve().parent
ANALYSIS = ROOT / "data" / "valuation.json"
HISTORY = ROOT / "data" / "history.json"
OUT = ROOT / "valuation.html"

_W, _H, _PAD = 200, 44, 4  # sparkline geometry


def score_color(score: float) -> str:
    """Green (cheap) -> amber (fair) -> red (extreme)."""
    if score < 20:
        return "#1a7f37"
    if score < 40:
        return "#4a9e4a"
    if score < 55:
        return "#b0902a"
    if score < 70:
        return "#d97706"
    if score < 85:
        return "#e0562b"
    return "#c1121f"


def sparkline(series: dict, color: str) -> str:
    """Return an inline SVG 1-year sparkline for one indicator series."""
    pts = series.get("points", [])
    if len(pts) < 2:
        return ""
    ys = [p[1] for p in pts]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    n = len(pts)
    xs = [_PAD + i * (_W - 2 * _PAD) / (n - 1) for i in range(n)]

    def yv(v: float) -> float:
        return _H - _PAD - (v - lo) / span * (_H - 2 * _PAD)

    coords = [(xs[i], yv(ys[i])) for i in range(n)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (f"{coords[0][0]:.1f},{_H - _PAD} " + line +
            f" {coords[-1][0]:.1f},{_H - _PAD}")
    lx, ly = coords[-1]
    first, last = ys[0], ys[-1]
    delta = last - first
    pct = (delta / first * 100) if first else 0.0
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "→")
    gid = f"g{abs(hash(tuple(ys))) % 100000}"
    unit = html.escape(series.get("unit", ""))
    src = html.escape(series.get("source", ""))
    return f"""
    <div class="spark">
      <svg viewBox="0 0 {_W} {_H}" width="100%" height="{_H}" preserveAspectRatio="none"
           role="img" aria-label="Historique 1 an">
        <defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="{color}" stop-opacity="0.22"/>
          <stop offset="1" stop-color="{color}" stop-opacity="0"/>
        </linearGradient></defs>
        <polygon points="{area}" fill="url(#{gid})" stroke="none"/>
        <polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.6"
                  stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.6" fill="{color}"/>
      </svg>
      <div class="spark-cap">
        <span>1 an&nbsp;: <b style="color:{color}">{arrow} {delta:+.2g}{unit}</b>
          ({pct:+.1f}%)</span>
        <span class="range">{lo:g}–{hi:g}{unit}</span>
        <span class="src">{src}</span>
      </div>
    </div>"""


def main() -> None:
    if not ANALYSIS.exists():
        raise SystemExit("data/valuation.json manquant — lancez d'abord "
                         "`python valuation_engine.py`.")
    a = json.loads(ANALYSIS.read_text())
    history = {}
    if HISTORY.exists():
        history = json.loads(HISTORY.read_text()).get("series", {})

    rows = []
    for r in a["indicators"]:
        col = score_color(r["score"])
        val = f'{r["value"]:g}{html.escape(r["unit"])}'
        spark = sparkline(history[r["key"]], col) if r["key"] in history else ""
        rows.append(f"""
  <div class="ind">
    <div class="ind-head">
      <span class="ind-label">{html.escape(r["label"])}</span>
      <span class="ind-val">{val}</span>
    </div>
    <div class="track"><div class="fill" style="width:{r['score']}%;background:{col}"></div></div>
    <div class="ind-foot">
      <span class="score" style="color:{col}">{r['score']:g}/100 · {html.escape(r['assessment'])}</span>
      <span class="fam">{html.escape(FAMILIES.get(r['family'], r['family']))}</span>
    </div>
    {spark}
    <p class="note">{html.escape(r["note"])}</p>
  </div>""")

    fam_chips = []
    for fam, name in FAMILIES.items():
        if fam in a["family_scores"]:
            s = a["family_scores"][fam]
            fam_chips.append(
                f'<span class="chip" style="border-color:{score_color(s)}">'
                f'{html.escape(name)} <b>{s:g}</b></span>')

    comp = a["composite_score"]
    comp_col = a.get("color", score_color(comp))
    fwd = a["expected_10y_real_return_pct"]
    fwd_html = (f'<div class="fwd">Rendement réel 10 ans estimé (via CAPE) : '
                f'<b>{fwd:+.1f} % / an</b></div>' if fwd is not None else "")

    OUT.write_text(f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moteur d'analyse de valorisation — marché actions</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         max-width: 860px; margin: 2em auto; padding: 0 1em; line-height: 1.5; }}
  header {{ border-bottom: 1px solid #ccc; padding-bottom: 0.6em; margin-bottom: 1.2em; }}
  h1 {{ margin: 0; font-size: 1.4em; }}
  .meta {{ color: #888; font-size: 0.82em; }}
  .gauge {{ text-align: center; margin: 1.4em 0; padding: 1.2em;
           border-radius: 10px; background: rgba(127,127,127,0.08); }}
  .gauge .big {{ font-size: 3.2em; font-weight: 800; line-height: 1;
                color: {comp_col}; }}
  .gauge .big small {{ font-size: 0.3em; color: #999; font-weight: 500; }}
  .verdict {{ font-size: 1.15em; font-weight: 700; margin: 0.3em 0 0.1em; color: {comp_col}; }}
  .stance {{ color: #666; font-size: 0.95em; max-width: 46ch; margin: 0.2em auto 0; }}
  .master {{ height: 12px; border-radius: 6px; background: rgba(127,127,127,0.25);
            margin: 0.9em auto 0; max-width: 520px; overflow: hidden; }}
  .master > div {{ height: 100%; width: {comp}%; background: {comp_col}; }}
  .fwd {{ margin-top: 0.8em; font-size: 0.92em; color: #555; }}
  .chips {{ text-align: center; margin: 0 0 1.4em; }}
  .chip {{ display: inline-block; border: 2px solid #ccc; border-radius: 999px;
          padding: 0.15em 0.7em; margin: 0.2em; font-size: 0.85em; }}
  .chip b {{ margin-left: 0.2em; }}
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
  .spark {{ margin: 0.55em 0 0.15em; }}
  .spark svg {{ display: block; border-radius: 4px; background: rgba(127,127,127,0.05); }}
  .spark-cap {{ display: flex; flex-wrap: wrap; gap: 0.2em 0.9em; font-size: 0.74em;
               color: #888; margin-top: 0.2em; }}
  .spark-cap .range {{ font-variant-numeric: tabular-nums; }}
  .spark-cap .src {{ margin-left: auto; font-style: italic; opacity: 0.8; }}
  .note {{ font-size: 0.82em; color: #777; margin: 0.4em 0 0; }}
  footer {{ margin-top: 2em; font-size: 0.75em; color: #999; border-top: 1px solid #ddd;
           padding-top: 0.8em; }}
</style>
</head>
<body>
<header>
  <h1>Moteur d'analyse de valorisation — marché actions</h1>
  <div class="meta">Généré : {html.escape(a["generated_at"])}</div>
</header>

<div class="gauge">
  <div class="big">{comp:g}<small>/100</small></div>
  <div class="verdict">{html.escape(a["verdict"])}</div>
  <p class="stance">{html.escape(a["stance"])}</p>
  <div class="master"><div></div></div>
  {fwd_html}
</div>

<div class="chips">{''.join(fam_chips)}</div>

{''.join(rows)}

<footer>
  Ces indicateurs mesurent la valorisation et le régime du <b>marché actions
  global</b>, pas une action individuelle. Le score composite décrit le contexte
  macro dans lequel s'inscrit toute décision sur un titre — à combiner avec
  l'analyse propre à l'entreprise (croissance, marges, dette, valorisation
  relative). Outil d'orientation, pas un conseil en investissement.
</footer>
</body>
</html>
""")
    print(f"rendered dashboard -> {OUT}")


if __name__ == "__main__":
    main()
