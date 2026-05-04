"""Audit of the target domain's current organic positioning."""

from __future__ import annotations

import pandas as pd

from ..ahrefs_client import AhrefsClient
from ..scoring import opportunity_score, resolve_intent


def fetch_positioning(
    client: AhrefsClient,
    target: str,
    *,
    min_volume: int = 50,
    limit: int = 5000,
) -> pd.DataFrame:
    rows = client.organic_keywords(
        target,
        limit=limit,
        where=f"volume>={min_volume},position<=100",
        order_by="traffic:desc",
    )
    if not rows:
        return pd.DataFrame(
            columns=[
                "keyword", "volume", "kd", "position", "url", "traffic",
                "cpc", "intent", "parent_topic", "opportunity_score",
            ]
        )

    df = pd.DataFrame(rows)
    df = df.rename(
        columns={
            "keyword_difficulty": "kd",
            "intents": "intent_raw",
            "parent_topic": "parent_topic",
        }
    )
    df["intent"] = df.apply(
        lambda r: resolve_intent(r.get("keyword", ""), r.get("intent_raw")),
        axis=1,
    )
    df["opportunity_score"] = df.apply(
        lambda r: opportunity_score(r.get("volume", 0), r.get("kd", 0), r["intent"]),
        axis=1,
    )

    keep = [
        "keyword", "volume", "kd", "position", "url", "traffic",
        "cpc", "intent", "parent_topic", "opportunity_score",
    ]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    return df[keep].sort_values("traffic", ascending=False, na_position="last")
