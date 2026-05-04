"""Content gap: keywords where competitors rank top 10 but the target doesn't.

If the Ahrefs plan exposes a native `content-gap` endpoint, prefer that.
Otherwise we emulate it by intersecting per-competitor `organic-keywords`.
"""

from __future__ import annotations

import pandas as pd

from ..ahrefs_client import AhrefsClient, AhrefsError
from ..scoring import opportunity_score, resolve_intent


def _fetch_competitor_top10(
    client: AhrefsClient, domain: str, *, min_volume: int = 300
) -> pd.DataFrame:
    rows = client.organic_keywords(
        domain,
        limit=5000,
        where=f"volume>={min_volume},position<=10",
        order_by="volume:desc",
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).rename(columns={"keyword_difficulty": "kd"})
    df["competitor"] = domain
    return df


def find_content_gap(
    client: AhrefsClient,
    target: str,
    competitors: list[str],
    *,
    min_volume: int = 300,
    max_kd: int = 40,
    min_competitors: int = 2,
) -> pd.DataFrame:
    """Keywords where ≥ `min_competitors` competitors rank top 10 and target doesn't."""
    target_kws_rows = client.organic_keywords(
        target, limit=10000, where="position<=100", order_by="volume:desc"
    )
    target_keywords = {
        r.get("keyword", "").strip().lower()
        for r in target_kws_rows
        if r.get("keyword")
    }

    competitor_frames = []
    for domain in competitors:
        try:
            competitor_frames.append(
                _fetch_competitor_top10(client, domain, min_volume=min_volume)
            )
        except AhrefsError as exc:
            print(f"[content_gap] skipping {domain}: {exc}")

    if not competitor_frames:
        return pd.DataFrame()

    combined = pd.concat(competitor_frames, ignore_index=True)
    if combined.empty:
        return combined

    combined["keyword_lc"] = combined["keyword"].str.lower().str.strip()
    combined = combined[~combined["keyword_lc"].isin(target_keywords)]

    agg = (
        combined.groupby("keyword_lc")
        .agg(
            keyword=("keyword", "first"),
            volume=("volume", "max"),
            kd=("kd", "max"),
            cpc=("cpc", "max"),
            parent_topic=("parent_topic", "first"),
            intent_raw=("intents", "first") if "intents" in combined.columns else ("keyword", "first"),
            competitors_ranking=("competitor", lambda s: ",".join(sorted(set(s)))),
            n_competitors=("competitor", "nunique"),
        )
        .reset_index(drop=True)
    )

    agg = agg[(agg["n_competitors"] >= min_competitors) & (agg["kd"] <= max_kd)]
    agg["intent"] = agg.apply(
        lambda r: resolve_intent(r["keyword"], r.get("intent_raw")), axis=1
    )
    agg["opportunity_score"] = agg.apply(
        lambda r: opportunity_score(r["volume"], r["kd"], r["intent"]), axis=1
    )

    keep = [
        "keyword", "volume", "kd", "cpc", "intent", "parent_topic",
        "n_competitors", "competitors_ranking", "opportunity_score",
    ]
    return agg[keep].sort_values("opportunity_score", ascending=False)
