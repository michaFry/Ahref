"""Markdown synthesis report."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def _section_top_quick_wins(df: pd.DataFrame, top: int = 20) -> str:
    if df.empty:
        return "_Aucun quick win identifié._\n"
    head = df.head(top)
    lines = [
        "| # | Mot-clé | Pos. | Vol. | KD | Trafic actuel | Uplift estimé | URL |",
        "|---|---------|------|------|----|--------------:|--------------:|-----|",
    ]
    for i, row in enumerate(head.itertuples(index=False), 1):
        lines.append(
            f"| {i} | {row.keyword} | {int(row.position) if pd.notna(row.position) else '-'} | "
            f"{int(row.volume) if pd.notna(row.volume) else '-'} | "
            f"{int(row.kd) if pd.notna(row.kd) else '-'} | "
            f"{int(row.traffic) if pd.notna(row.traffic) else '-'} | "
            f"{getattr(row, 'potential_traffic_uplift', '-')} | {row.url or '-'} |"
        )
    return "\n".join(lines) + "\n"


def _section_top_thematic(df: pd.DataFrame, top: int = 30) -> str:
    if df.empty:
        return "_Aucun mot-clé thématique identifié._\n"
    parts: list[str] = []
    for theme, group in df.groupby("theme"):
        head = group.head(max(1, top // max(df["theme"].nunique(), 1)))
        parts.append(f"### Cluster `{theme}`\n")
        parts.append(
            "| Mot-clé | Vol. | KD | Intent | Question ? | Score |\n"
            "|---------|-----:|---:|--------|:----------:|------:|"
        )
        for row in head.itertuples(index=False):
            parts.append(
                f"| {row.keyword} | {int(row.volume) if pd.notna(row.volume) else '-'} | "
                f"{int(row.kd) if pd.notna(row.kd) else '-'} | {row.intent} | "
                f"{'oui' if getattr(row, 'is_question', False) else ''} | "
                f"{row.opportunity_score} |"
            )
        parts.append("")
    return "\n".join(parts)


def _section_pillars(thematic_df: pd.DataFrame, n: int = 10) -> str:
    """Group thematic keywords by parent_topic and pick the strongest cluster."""
    if thematic_df.empty:
        return "_Données insuffisantes pour proposer des piliers._\n"
    df = thematic_df.copy()
    df["parent_topic"] = df["parent_topic"].fillna(df["keyword"])
    grouped = (
        df.groupby("parent_topic")
        .agg(
            theme=("theme", "first"),
            total_volume=("volume", "sum"),
            avg_kd=("kd", "mean"),
            keywords=("keyword", lambda s: list(s)[:6]),
        )
        .reset_index()
        .sort_values("total_volume", ascending=False)
        .head(n)
    )
    lines = []
    for i, row in enumerate(grouped.itertuples(index=False), 1):
        kws = row.keywords
        primary = kws[0] if kws else row.parent_topic
        secondary = ", ".join(kws[1:6])
        lines.append(
            f"{i}. **{primary}** _(cluster `{row.theme}`, volume cumulé "
            f"{int(row.total_volume)}, KD moyen {row.avg_kd:.0f})_  \n"
            f"   Mots-clés secondaires : {secondary or '-'}"
        )
    return "\n".join(lines) + "\n"


def _estimate_traffic_uplift(quick_wins: pd.DataFrame, content_gap: pd.DataFrame) -> str:
    qw_uplift = 0
    if not quick_wins.empty and "potential_traffic_uplift" in quick_wins.columns:
        qw_uplift = quick_wins["potential_traffic_uplift"].sum()

    gap_uplift = 0
    if not content_gap.empty:
        gap = content_gap.copy()
        gap["volume"] = pd.to_numeric(gap["volume"], errors="coerce").fillna(0)
        gap_uplift = (gap["volume"] * 0.05).sum()

    total = int(qw_uplift + gap_uplift)
    return (
        f"- Quick wins (passage en top 3) : ~**{int(qw_uplift):,}** visites/mois\n"
        f"- Content gap (capture position 5-10) : ~**{int(gap_uplift):,}** visites/mois\n"
        f"- **Total potentiel additionnel : ~{total:,} visites/mois**\n"
    ).replace(",", " ")


def render_report(
    *,
    target_domain: str,
    positioning_df: pd.DataFrame,
    quick_wins_df: pd.DataFrame,
    content_gap_df: pd.DataFrame,
    thematic_df: pd.DataFrame,
    output_path: Path,
) -> Path:
    today = date.today().isoformat()
    n_kw = len(positioning_df)
    n_qw = len(quick_wins_df)
    n_gap = len(content_gap_df)
    n_them = len(thematic_df)

    md = f"""# Rapport SEO — {target_domain}
_Généré le {today}_

## Vue d'ensemble
- Mots-clés positionnés (volume ≥ 50, top 100) : **{n_kw}**
- Quick wins (positions 4-20, KD ≤ 30) : **{n_qw}**
- Mots-clés du content gap : **{n_gap}**
- Mots-clés thématiques découverts : **{n_them}**

## Estimation du trafic potentiel additionnel
{_estimate_traffic_uplift(quick_wins_df, content_gap_df)}

## Top 20 quick wins
{_section_top_quick_wins(quick_wins_df, top=20)}
**Recommandations d'action :**
- Réécrire le H1 et la meta description pour intégrer la requête exacte
- Enrichir le contenu (FAQ, exemples chiffrés, table des matières)
- Renforcer le maillage interne depuis les pages à forte autorité
- Ajouter données structurées (FAQ, HowTo) si pertinent

## Top mots-clés thématiques par cluster
{_section_top_thematic(thematic_df, top=30)}

## 10 articles piliers proposés
{_section_pillars(thematic_df, n=10)}

## Notes méthodologiques
- Score d'opportunité = (volume × intent_weight) / (KD + 1)
- Intent weights : transactional 1.5 · commercial 1.3 · informational 1.0 · navigational 0.5
- L'estimation d'uplift quick wins suppose un passage en position 3 (CTR ~10 %).
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")
    print(f"[md] wrote -> {output_path}")
    return output_path
