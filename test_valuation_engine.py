#!/usr/bin/env python3
"""Unit tests for the valuation engine. Run: python test_valuation_engine.py"""
from __future__ import annotations

from valuation_engine import (
    INDICATORS_BY_KEY,
    analyze,
    band_for,
    expected_10y_real_return,
    interpolate,
)


def approx(a: float, b: float, tol: float = 0.5) -> bool:
    return abs(a - b) <= tol


def test_interpolate_endpoints_and_clamp():
    anchors = [(0, 0), (10, 100)]
    assert interpolate(0, anchors) == 0
    assert interpolate(10, anchors) == 100
    assert interpolate(5, anchors) == 50
    assert interpolate(-5, anchors) == 0    # clamped low
    assert interpolate(99, anchors) == 100  # clamped high


def test_scores_are_monotonic_for_valuation_gauges():
    # For a pure "higher is richer" gauge, score must be non-decreasing.
    cape = INDICATORS_BY_KEY["shiller_cape"]
    prev = -1.0
    for v in [10, 17, 22, 27, 32, 37, 45]:
        s = cape.score(v)
        assert s >= prev, f"CAPE score not monotonic at {v}"
        prev = s


def test_vix_is_u_shaped():
    # Both extreme calm and extreme fear should score higher than a normal 20.
    vix = INDICATORS_BY_KEY["vix"]
    assert vix.score(10) > vix.score(20)   # complacency > normal
    assert vix.score(45) < vix.score(20)   # fear = contrarian, low stretch


def test_hy_spread_is_u_shaped():
    hy = INDICATORS_BY_KEY["hy_credit_spread"]
    assert hy.score(2.0) > hy.score(4.5)   # very tight = complacency
    assert hy.score(12.0) > hy.score(4.5)  # very wide = distress


def test_band_boundaries():
    assert band_for(10).verdict.startswith("Fortement")
    assert band_for(50).verdict.startswith("Proche")
    assert band_for(100).verdict.startswith("Survalorisation extrême")


def test_expected_return_falls_with_cape():
    assert expected_10y_real_return(15) > expected_10y_real_return(45)
    assert expected_10y_real_return(None) is None
    assert expected_10y_real_return(0) is None


def test_full_analysis_current_readings():
    readings = {
        "shiller_cape": 41.6,
        "buffett_indicator": 218,
        "tobins_q": 1.82,
        "sp500_m2": 0.325,
        "margin_debt_m2": 5.5,
        "hy_credit_spread": 2.74,
        "vix": 16.6,
        "yield_curve_10y2y": 0.35,
    }
    a = analyze(readings)
    # These readings are historically extreme -> composite must land high.
    assert a["composite_score"] > 70, a["composite_score"]
    assert len(a["indicators"]) == 8
    assert set(a["family_scores"]) == {"valuation", "sentiment", "cycle"}
    assert a["expected_10y_real_return_pct"] is not None


def test_partial_input_renormalises():
    a = analyze({"shiller_cape": 22})  # single fair-ish valuation gauge
    assert len(a["indicators"]) == 1
    assert 40 <= a["composite_score"] <= 60


def test_undervalued_scenario():
    readings = {
        "shiller_cape": 12,
        "buffett_indicator": 70,
        "tobins_q": 0.6,
        "vix": 35,
        "hy_credit_spread": 6.0,
        "yield_curve_10y2y": 2.0,
    }
    a = analyze(readings)
    assert a["composite_score"] < 40, a["composite_score"]


def run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passés.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
