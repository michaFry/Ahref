"""Identify keywords ranking 4-20 with reasonable volume and low KD."""

from __future__ import annotations

import pandas as pd


def estimate_potential_traffic(volume: float, position: float) -> float:
    """Rough CTR uplift estimate if the page reaches position 3."""
    ctr_curve = {
        1: 0.30, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
        6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.018,
    }
    p = int(position) if position else 100
    current_ctr = ctr_curve.get(p, 0.005 if p > 10 else 0.01)
    target_ctr = ctr_curve[3]
    uplift = max(target_ctr - current_ctr, 0)
    return round(float(volume or 0) * uplift, 1)


def find_quick_wins(
    positioning_df: pd.DataFrame,
    *,
    min_volume: int = 200,
    max_kd: int = 30,
    position_range: tuple[int, int] = (4, 20),
    allowed_intents: tuple[str, ...] = ("informational", "transactional", "commercial"),
) -> pd.DataFrame:
    if positioning_df.empty:
        return positioning_df.copy()

    lo, hi = position_range
    df = positioning_df.copy()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df["kd"] = pd.to_numeric(df["kd"], errors="coerce").fillna(100)
    df["position"] = pd.to_numeric(df["position"], errors="coerce").fillna(101)

    mask = (
        (df["position"] >= lo)
        & (df["position"] <= hi)
        & (df["volume"] >= min_volume)
        & (df["kd"] <= max_kd)
        & (df["intent"].isin(allowed_intents))
    )
    qw = df.loc[mask].copy()
    qw["potential_traffic_uplift"] = qw.apply(
        lambda r: estimate_potential_traffic(r["volume"], r["position"]), axis=1
    )
    return qw.sort_values("potential_traffic_uplift", ascending=False)
