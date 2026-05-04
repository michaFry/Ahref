"""Thematic keyword discovery via Keywords Explorer matching-terms."""

from __future__ import annotations

import pandas as pd

from ..ahrefs_client import AhrefsClient, AhrefsError
from ..scoring import opportunity_score, resolve_intent

THEMES: dict[str, list[str]] = {
    "lmnp": [
        "LMNP", "LMNP 2026", "réforme LMNP", "fiscalité LMNP", "LMP vs LMNP",
        "déclaration LMNP", "amortissement LMNP",
    ],
    "viager_vente_a_terme": [
        "viager", "vente à terme", "viager occupé", "viager libre",
        "calcul viager", "fiscalité viager", "bouquet viager",
    ],
    "independance_financiere": [
        "indépendance financière", "FIRE", "retraite anticipée",
        "rente passive", "revenu passif", "liberté financière",
    ],
    "bourse_long_terme": [
        "investir en bourse long terme", "ETF", "PEA", "DCA",
        "dividendes", "investir CW8", "MSCI World",
    ],
    "credit_immobilier": [
        "HCSF", "taux usure", "capacité d'emprunt", "DSCR",
        "endettement 35%", "crédit immobilier", "renégocier prêt",
    ],
}


def _seed_to_dataframe(rows: list[dict], theme: str, seed: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).rename(columns={"keyword_difficulty": "kd"})
    df["theme"] = theme
    df["seed"] = seed
    return df


def discover_thematic_keywords(
    client: AhrefsClient,
    *,
    themes: dict[str, list[str]] | None = None,
    limit_per_seed: int = 100,
    min_volume: int = 100,
    max_kd: int = 50,
) -> pd.DataFrame:
    themes = themes or THEMES
    frames: list[pd.DataFrame] = []

    for theme, seeds in themes.items():
        for seed in seeds:
            try:
                rows = client.matching_terms(
                    seed,
                    limit=limit_per_seed,
                    match_mode="terms",
                    where=f"volume>={min_volume},keyword_difficulty<={max_kd}",
                )
            except AhrefsError as exc:
                print(f"[thematic] {theme}/{seed}: {exc}")
                continue
            frames.append(_seed_to_dataframe(rows, theme, seed))

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df

    df["keyword_lc"] = df["keyword"].str.lower().str.strip()
    df = df.sort_values("volume", ascending=False).drop_duplicates("keyword_lc")
    df["intent"] = df.apply(
        lambda r: resolve_intent(r["keyword"], r.get("intents")), axis=1
    )
    df["is_question"] = df["keyword_lc"].str.match(
        r"^(comment|pourquoi|qu['e]st-ce|quoi|est-ce|combien|quand|où|qui)\b"
    )
    df["opportunity_score"] = df.apply(
        lambda r: opportunity_score(r.get("volume", 0), r.get("kd", 0), r["intent"]),
        axis=1,
    )

    keep = [
        "theme", "seed", "keyword", "volume", "kd", "cpc", "intent",
        "is_question", "parent_topic", "opportunity_score",
    ]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    return df[keep].sort_values(["theme", "opportunity_score"], ascending=[True, False])
