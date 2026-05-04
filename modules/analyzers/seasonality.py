"""Optional: detect seasonal keywords using volume_history."""

from __future__ import annotations

import statistics

import pandas as pd

from ..ahrefs_client import AhrefsClient, AhrefsError


def seasonal_coefficient(history: list[dict]) -> tuple[float, int | None]:
    """Return (peak/median ratio, peak month) from a volume_history payload."""
    if not history:
        return 0.0, None
    monthly = {}
    for row in history:
        month = row.get("month") or row.get("date", "")[5:7]
        try:
            month_int = int(month)
        except (TypeError, ValueError):
            continue
        v = float(row.get("volume", 0) or 0)
        monthly.setdefault(month_int, []).append(v)
    if not monthly:
        return 0.0, None
    monthly_avg = {m: sum(vs) / len(vs) for m, vs in monthly.items()}
    median = statistics.median(monthly_avg.values()) or 1
    peak_month, peak_value = max(monthly_avg.items(), key=lambda x: x[1])
    return round(peak_value / median, 2), peak_month


def annotate_seasonality(
    client: AhrefsClient,
    keywords_df: pd.DataFrame,
    *,
    threshold: float = 1.5,
    limit: int = 100,
) -> pd.DataFrame:
    if keywords_df.empty:
        return keywords_df.copy()
    head = keywords_df.head(limit).copy()
    coefs: list[float] = []
    peaks: list[int | None] = []
    for kw in head["keyword"].tolist():
        try:
            history = client.volume_history(kw)
        except AhrefsError:
            history = []
        coef, peak = seasonal_coefficient(history)
        coefs.append(coef)
        peaks.append(peak)
    head["seasonality_coef"] = coefs
    head["peak_month"] = peaks
    head["is_seasonal"] = head["seasonality_coef"] >= threshold
    return head
