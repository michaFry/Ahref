#!/usr/bin/env python3
"""Market valuation engine.

Scores a set of macro / market-wide valuation and risk-sentiment indicators
into a single composite "how expensive & how complacent is the equity market"
reading, plus a CAPE-based estimate of forward 10-year real returns.

The seven indicators handled here (Shiller CAPE, Buffett indicator, Tobin's Q,
S&P 500 / M2, high-yield credit spread, VIX, 10y-2y yield curve) are *market
level* gauges, not single-stock metrics. The engine therefore describes the
macro backdrop an equity sits in — the regime in which any individual stock
decision is taken — not the intrinsic value of one company.

Scoring convention
------------------
Every indicator is mapped to a 0-100 "stretch" score via piecewise-linear
interpolation over hand-set anchor points:

    0   = cheap / calm  -> favourable for forward returns
    50  = around fair value / neutral
    100 = extreme overvaluation or extreme complacency -> poor forward returns

Contrarian gauges (VIX, HY spread) are U-shaped: both extreme calm
(complacency, late-cycle froth) and extreme stress (distress) score high, while
"normal" middle readings score low. The anchor tables encode that shape.

The composite is a weighted average of the per-indicator scores, with the
three most historically reliable valuation gauges (CAPE, Buffett, Tobin's Q)
carrying the most weight.

Usage
-----
    python valuation_engine.py [data/indicators.json]

With no argument it falls back to data/indicators.json. It prints a report to
stdout and writes the full structured analysis to data/valuation.json.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "indicators.json"
DEFAULT_OUTPUT = ROOT / "data" / "valuation.json"


# --------------------------------------------------------------------------
# Piecewise-linear interpolation over (value, score) anchor points.
# --------------------------------------------------------------------------
def interpolate(value: float, anchors: list[tuple[float, float]]) -> float:
    """Map ``value`` to a score by linear interpolation between anchor points.

    ``anchors`` is a list of (input, score) pairs sorted by input. Values
    outside the anchor range are clamped to the nearest endpoint score, so the
    output always stays within the score bounds defined by the table.
    """
    pts = sorted(anchors, key=lambda p: p[0])
    if value <= pts[0][0]:
        return pts[0][1]
    if value >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            frac = (value - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return pts[-1][1]  # unreachable, keeps type checkers happy


# --------------------------------------------------------------------------
# Indicator definitions.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Indicator:
    key: str
    label: str
    unit: str
    weight: float
    family: str  # "valuation" | "sentiment" | "cycle"
    anchors: list[tuple[float, float]]
    # Whether a *higher* raw reading is normally the expensive/risky direction.
    # Purely informational (used for the arrow shown in reports).
    higher_is_richer: bool
    note: str = ""
    scorer: Callable[[float], float] | None = None

    def score(self, value: float) -> float:
        if self.scorer is not None:
            return self.scorer(value)
        return interpolate(value, self.anchors)


# Anchor tables. Score 0 = cheap/calm/favourable, 100 = extreme stretch/risk.
INDICATORS: list[Indicator] = [
    Indicator(
        key="shiller_cape",
        label="Shiller CAPE Ratio",
        unit="x",
        weight=1.5,
        family="valuation",
        higher_is_richer=True,
        anchors=[(10, 0), (17, 32), (22, 52), (27, 68), (32, 80), (37, 90), (45, 100)],
        note="Prix / bénéfices réels lissés sur 10 ans. >30-35 historiquement "
             "associé à des rendements décennaux faibles.",
    ),
    Indicator(
        key="buffett_indicator",
        label="Buffett Indicator (Mkt Cap / GDP)",
        unit="%",
        weight=1.5,
        family="valuation",
        higher_is_richer=True,
        anchors=[(60, 0), (90, 32), (115, 58), (140, 76), (170, 90), (220, 100)],
        note="Capitalisation boursière totale / PIB. >100-150 % signale une "
             "survalorisation.",
    ),
    Indicator(
        key="tobins_q",
        label="Tobin's Q",
        unit="",
        weight=1.3,
        family="valuation",
        higher_is_richer=True,
        anchors=[(0.5, 0), (0.75, 34), (1.0, 55), (1.3, 75), (1.6, 90), (2.0, 100)],
        note="Valeur de marché / coût de remplacement des actifs. >1 = les "
             "actions coûtent plus que reconstruire les entreprises.",
    ),
    Indicator(
        key="sp500_m2",
        label="S&P 500 / M2",
        unit="",
        weight=0.8,
        family="valuation",
        higher_is_richer=True,
        anchors=[(0.15, 0), (0.22, 34), (0.28, 60), (0.33, 80), (0.40, 100)],
        note="Actions relatives à la masse monétaire. Neutralise une partie "
             "de l'effet monétaire sur les cours.",
    ),
    Indicator(
        key="margin_debt_m2",
        label="Margin Debt / M2",
        unit="%",
        weight=0.9,
        family="sentiment",
        higher_is_richer=True,
        anchors=[(2.0, 0), (2.8, 20), (3.5, 40), (4.2, 60), (4.8, 75), (5.5, 88), (6.3, 100)],
        note="Dette sur marge (effet de levier des investisseurs) / masse "
             "monétaire M2. Les pics de levier accompagnent les sommets de "
             "marché (2000, 2007, 2021).",
    ),
    Indicator(
        key="hy_credit_spread",
        label="High-yield credit spread",
        unit="pp",
        weight=0.7,
        family="sentiment",
        higher_is_richer=False,
        # U-shaped: very tight = complacency (high score), normal = calm (low),
        # very wide = distress (high again).
        anchors=[(1.8, 92), (2.75, 74), (3.5, 52), (5.0, 45), (8.0, 75), (12.0, 100)],
        note="Spreads serrés = risque de crédit perçu faible et complaisance "
             "('froth'). Spreads larges = stress.",
    ),
    Indicator(
        key="vix",
        label="VIX",
        unit="",
        weight=0.6,
        family="sentiment",
        higher_is_richer=False,
        # U-shaped: low VIX = complacency (rich), high VIX = fear (often a
        # contrarian buy, so low stretch score).
        anchors=[(9, 88), (13, 78), (16.5, 68), (20, 50), (30, 30), (45, 15), (60, 25)],
        note="VIX bas = complaisance, fréquent en fin de cycle. Pics = peur "
             "(souvent contrarien haussier).",
    ),
    Indicator(
        key="yield_curve_10y2y",
        label="Yield curve (10y-2y)",
        unit="pp",
        weight=0.9,
        family="cycle",
        higher_is_richer=False,
        # Inversion (negative) is the recession warning; a fresh, barely
        # positive curve after an inversion is still late-cycle caution; a
        # steep positive curve is healthy early-cycle.
        anchors=[(-1.5, 90), (-0.5, 82), (0.0, 72), (0.5, 58), (1.2, 35), (2.5, 15)],
        note="Inversion (négatif) précède souvent une récession de 6-24 mois. "
             "Un désinversement récent reste un signal de fin de cycle.",
    ),
]

INDICATORS_BY_KEY = {ind.key: ind for ind in INDICATORS}


# --------------------------------------------------------------------------
# Verdict bands for the composite score.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Band:
    lo: float
    hi: float
    verdict: str
    stance: str
    color: str


BANDS: list[Band] = [
    Band(0, 20, "Fortement sous-valorisé",
         "Accumulation agressive — contexte très favorable aux rendements futurs.",
         "#1a7f37"),
    Band(20, 40, "Sous-valorisé / attractif",
         "Surpondérer les actions ; bon point d'entrée historique.",
         "#4a9e4a"),
    Band(40, 55, "Proche de la juste valeur",
         "Pondération neutre ; rester investi, sélectif.",
         "#b0902a"),
    Band(55, 70, "Tendu / prudence",
         "Réduire le risque à la marge, privilégier la qualité et les marges de sécurité.",
         "#d97706"),
    Band(70, 85, "Survalorisé",
         "Posture défensive : cash, value, faible duration ; attentes de rendement basses.",
         "#e0562b"),
    Band(85, 100.0001, "Survalorisation extrême",
         "Risque élevé de rendements décennaux faibles ou négatifs ; protection du capital prioritaire.",
         "#c1121f"),
]


def band_for(score: float) -> Band:
    for b in BANDS:
        if b.lo <= score < b.hi:
            return b
    return BANDS[-1]


# --------------------------------------------------------------------------
# CAPE-based forward return estimate.
# --------------------------------------------------------------------------
def expected_10y_real_return(cape: float | None) -> float | None:
    """Rough estimate of annualised 10y real return from CAPE.

    Uses the well-known empirical relationship that forward real returns fall
    roughly linearly with the log of CAPE. Coefficients are a coarse fit to the
    historical US pattern (high CAPE -> low/negative forward real returns) and
    are meant for orientation, not precision.
    """
    if cape is None or cape <= 0:
        return None
    # ~ intercept - slope * ln(CAPE); calibrated so CAPE 15 -> ~7%, 25 -> ~3%,
    # 35 -> ~0.5%, 45 -> ~-1.5%.
    est = 0.26 - 0.083 * math.log(cape)
    return round(est * 100, 2)


# --------------------------------------------------------------------------
# Engine.
# --------------------------------------------------------------------------
@dataclass
class IndicatorResult:
    key: str
    label: str
    value: float
    unit: str
    score: float
    weight: float
    family: str
    assessment: str
    note: str


FAMILIES = {
    "valuation": "Valorisation",
    "sentiment": "Sentiment / risque",
    "cycle": "Cycle économique",
}


def _assessment(score: float) -> str:
    if score < 20:
        return "très bon marché"
    if score < 40:
        return "attractif"
    if score < 55:
        return "juste valeur"
    if score < 70:
        return "tendu"
    if score < 85:
        return "cher"
    return "extrême"


def analyze(readings: dict[str, float]) -> dict:
    """Run the engine over a dict of {indicator_key: raw_value}.

    Missing indicators are simply skipped (weights renormalise over whatever
    is present), so a partial set still produces a coherent composite.
    """
    results: list[IndicatorResult] = []
    for ind in INDICATORS:
        if ind.key not in readings or readings[ind.key] is None:
            continue
        value = float(readings[ind.key])
        s = round(ind.score(value), 1)
        results.append(IndicatorResult(
            key=ind.key, label=ind.label, value=value, unit=ind.unit,
            score=s, weight=ind.weight, family=ind.family,
            assessment=_assessment(s), note=ind.note,
        ))

    if not results:
        raise ValueError("Aucun indicateur reconnu dans les données fournies.")

    total_w = sum(r.weight for r in results)
    composite = round(sum(r.score * r.weight for r in results) / total_w, 1)
    band = band_for(composite)

    # Per-family sub-scores (weighted within the family).
    family_scores: dict[str, float] = {}
    for fam in FAMILIES:
        fam_res = [r for r in results if r.family == fam]
        if fam_res:
            fw = sum(r.weight for r in fam_res)
            family_scores[fam] = round(
                sum(r.score * r.weight for r in fam_res) / fw, 1)

    cape = readings.get("shiller_cape")
    fwd = expected_10y_real_return(float(cape) if cape is not None else None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "composite_score": composite,
        "verdict": band.verdict,
        "stance": band.stance,
        "color": band.color,
        "family_scores": family_scores,
        "expected_10y_real_return_pct": fwd,
        "indicators": [r.__dict__ for r in results],
    }


# --------------------------------------------------------------------------
# CLI reporting.
# --------------------------------------------------------------------------
def _bar(score: float, width: int = 24) -> str:
    filled = int(round(score / 100 * width))
    return "█" * filled + "·" * (width - filled)


def print_report(analysis: dict) -> None:
    print("=" * 62)
    print("  MOTEUR D'ANALYSE DE VALORISATION — CONTEXTE MARCHÉ ACTIONS")
    print("=" * 62)
    print(f"  Généré : {analysis['generated_at']}")
    print()
    for r in analysis["indicators"]:
        val = f"{r['value']:g}{r['unit']}"
        print(f"  {r['label']:<34} {val:>9}")
        print(f"    {_bar(r['score'])}  {r['score']:>5}/100  ({r['assessment']})")
    print("-" * 62)
    for fam, name in FAMILIES.items():
        if fam in analysis["family_scores"]:
            print(f"  {name:<22} {analysis['family_scores'][fam]:>5}/100")
    print("-" * 62)
    comp = analysis["composite_score"]
    print(f"  SCORE COMPOSITE        {_bar(comp)}  {comp}/100")
    print(f"  VERDICT   : {analysis['verdict']}")
    print(f"  POSTURE   : {analysis['stance']}")
    fwd = analysis["expected_10y_real_return_pct"]
    if fwd is not None:
        print(f"  Rendement réel 10 ans estimé (via CAPE) : {fwd:+.1f} % / an")
    print("=" * 62)


def main(argv: list[str]) -> int:
    in_path = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_INPUT
    if not in_path.exists():
        print(f"Fichier d'entrée introuvable : {in_path}", file=sys.stderr)
        print("Format attendu : JSON {\"shiller_cape\": 41.6, ...}", file=sys.stderr)
        return 1
    raw = json.loads(in_path.read_text())
    # Accept either a flat {key: value} map or {"indicators": {key: value}}.
    readings = raw.get("indicators", raw) if isinstance(raw, dict) else raw
    analysis = analyze(readings)
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
    print_report(analysis)
    print(f"\nAnalyse écrite -> {DEFAULT_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
