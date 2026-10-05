import pytest

from citecheck import metrics


def test_accuracy_and_macro_f1_three_class():
    gold = ["supports", "supports", "contradicts", "not_enough_info"]
    pred = ["supports", "contradicts", "contradicts", "not_enough_info"]
    assert metrics.accuracy(gold, pred) == 0.75
    # supports: P=1, R=0.5, F1=2/3; contradicts: P=0.5, R=1, F1=2/3; nei: F1=1
    assert metrics.macro_f1(gold, pred, ["supports", "contradicts", "not_enough_info"]) == pytest.approx((2/3 + 2/3 + 1) / 3)


def test_macro_f1_label_never_predicted_or_present_counts_as_zero():
    assert metrics.macro_f1(["a", "a"], ["a", "a"], ["a", "b"]) == pytest.approx(0.5)


def test_bootstrap_ci_brackets_point_estimate_and_is_deterministic():
    gold = ["x"] * 50 + ["y"] * 50
    pred = ["x"] * 40 + ["y"] * 10 + ["y"] * 50
    lo, hi = metrics.bootstrap_ci(gold, pred, metrics.accuracy, n=500, seed=0)
    assert lo < 0.9 < hi and 0.8 < lo and hi < 0.97
    assert (lo, hi) == metrics.bootstrap_ci(gold, pred, metrics.accuracy, n=500, seed=0)


def test_cost_per_1000_uses_reported_cost_else_token_prices():
    records = [{"cost_usd": 0.002, "usage": {"prompt_tokens": 100, "completion_tokens": 50}},
               {"cost_usd": 0.004, "usage": {"prompt_tokens": 100, "completion_tokens": 50}}]
    assert metrics.cost_per_1000(records, price=None) == pytest.approx(3.0)
    no_cost = [{"cost_usd": None, "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}]
    # $2/M input, $10/M output -> 0.002 + 0.005 = $0.007 per call -> $7 per 1,000
    assert metrics.cost_per_1000(no_cost, price={"input": 2.0, "output": 10.0}) == pytest.approx(7.0)


def test_pareto_frontier_keeps_models_not_beaten_on_both_cost_and_accuracy():
    points = {"cheap_bad": (0.1, 0.60), "cheap_good": (0.5, 0.80), "pricey_same": (5.0, 0.80),
              "pricey_best": (6.0, 0.90), "dominated": (1.0, 0.70)}
    assert metrics.pareto_frontier(points) == ["cheap_bad", "cheap_good", "pricey_best"]
