#!/usr/bin/env python3
"""Offline unit tests for the stock scoring logic (no network).

Run: python test_stock_engine.py
"""
from __future__ import annotations

from stock_engine import (
    METRICS,
    score_stock,
    stock_band_for,
    _combined_note,
    analyze_ticker,
)


def test_valuation_metric_monotonic():
    pe = next(m for m in METRICS if m.key == "trailing_pe")
    prev = -1.0
    for v in [8, 15, 22, 30, 45, 70]:
        from stock_engine import interpolate
        s = interpolate(v, pe.anchors)
        assert s >= prev
        prev = s


def test_quality_metric_inverted():
    # Higher margin must score LOWER (more favorable).
    from stock_engine import interpolate
    pm = next(m for m in METRICS if m.key == "profit_margins")
    assert interpolate(0.30, pm.anchors) < interpolate(0.05, pm.anchors)


def test_cheap_solid_stock_scores_low():
    f = {
        "trailing_pe": 10, "forward_pe": 9, "peg_ratio": 0.8,
        "price_to_sales": 1.5, "price_to_book": 1.2,
        "profit_margins": 0.22, "operating_margins": 0.25, "return_on_equity": 0.25,
        "revenue_growth": 0.12, "earnings_growth": 0.15,
        "debt_to_equity": 30, "current_ratio": 2.5,
    }
    r = score_stock(f)
    assert r["stock_score"] < 35, r["stock_score"]
    assert r["verdict"].startswith(("Attractif", "Raisonnable"))


def test_expensive_fragile_stock_scores_high():
    f = {
        "trailing_pe": 65, "forward_pe": 55, "peg_ratio": 4.0,
        "price_to_sales": 18, "price_to_book": 30,
        "profit_margins": 0.01, "operating_margins": 0.02, "return_on_equity": -0.05,
        "revenue_growth": -0.05, "earnings_growth": -0.20,
        "debt_to_equity": 350, "current_ratio": 0.6,
    }
    r = score_stock(f)
    assert r["stock_score"] > 75, r["stock_score"]
    assert r["verdict"].startswith("Très cher")


def test_partial_fundamentals_renormalise():
    r = score_stock({"trailing_pe": 20, "profit_margins": 0.15})
    assert r["n_metrics"] == 2
    assert 0 <= r["stock_score"] <= 100


def test_family_scores_present():
    f = {"trailing_pe": 20, "profit_margins": 0.15,
         "revenue_growth": 0.08, "debt_to_equity": 80}
    r = score_stock(f)
    assert set(r["family_scores"]) == {"valuation", "profitability", "growth", "solidity"}


def test_band_boundaries():
    assert stock_band_for(10).verdict.startswith("Attractif")
    assert stock_band_for(52).verdict.startswith("Neutre")
    assert stock_band_for(90).verdict.startswith("Très cher")


def test_combined_note_matrix():
    assert "favorable" in _combined_note(30, 40).lower()
    assert "plafonne" in _combined_note(30, 80).lower()
    assert "double survalorisation" in _combined_note(80, 80).lower()


def test_analyze_ticker_with_injected_macro(monkeypatch=None):
    # Bypass the network by monkeypatching fetch_fundamentals.
    import stock_engine
    fake = {
        "ticker": "TEST", "name": "Test Co", "sector": "Tech", "industry": "SW",
        "price": {"price": 100, "currency": "USD", "week52_high": 120,
                  "week52_low": 80, "market_cap": 1e9, "recommendation": "hold"},
        "fundamentals": {
            "trailing_pe": 18, "forward_pe": 16, "peg_ratio": 1.2,
            "price_to_sales": 3, "price_to_book": 4,
            "profit_margins": 0.15, "operating_margins": 0.18, "return_on_equity": 0.2,
            "revenue_growth": 0.1, "earnings_growth": 0.12,
            "debt_to_equity": 60, "current_ratio": 1.8,
        },
    }
    orig = stock_engine.fetch_fundamentals
    stock_engine.fetch_fundamentals = lambda t: fake
    try:
        a = analyze_ticker("TEST", macro_readings={"shiller_cape": 22, "vix": 20})
    finally:
        stock_engine.fetch_fundamentals = orig
    assert a["ticker"] == "TEST"
    assert a["macro"] is not None
    assert a["combined"] is not None
    # global = 0.6*stock + 0.4*macro, must lie between the two.
    lo, hi = sorted([a["stock"]["stock_score"], a["macro"]["composite_score"]])
    assert lo <= a["combined"]["global_score"] <= hi


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
