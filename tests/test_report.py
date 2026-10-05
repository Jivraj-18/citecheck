import pytest

from citecheck import report

ITEMS = {
    "scifact/1": {"id": "scifact/1", "dataset": "scifact", "label": "supports"},
    "scifact/2": {"id": "scifact/2", "dataset": "scifact", "label": "contradicts"},
    "arxiv/p/original": {"id": "arxiv/p/original", "dataset": "arxiv", "label": "supports"},
    "arxiv/p/swapped": {"id": "arxiv/p/swapped", "dataset": "arxiv", "label": "not_supported"},
}


def row(item, model, verdict, cost=0.001):
    return {"item_id": item, "model": model, "verdict": verdict, "cost_usd": cost,
            "usage": {"prompt_tokens": 500, "completion_tokens": 100}}


def test_per_model_scores_split_by_dataset_and_cost():
    rows = [row("scifact/1", "m", "supports"), row("scifact/2", "m", "supports"),
            row("arxiv/p/original", "m", "supports"), row("arxiv/p/swapped", "m", "not_enough_info"),
            {"item_id": "scifact/2", "model": "x", "error": "boom"}]
    out = report.model_summary(rows, ITEMS, "m", price=None, bootstrap=200)
    assert out["scifact"]["accuracy"] == 0.5 and out["scifact"]["n"] == 2
    assert out["arxiv"]["accuracy"] == 1.0  # not_enough_info on a swapped pair counts as "not supported"
    assert out["cost_per_1000_usd"] == pytest.approx(1.0)
    assert out["errors"] == 0
    lo, hi = out["scifact"]["accuracy_ci"]
    assert lo <= 0.5 <= hi


def test_errors_are_counted_and_excluded_from_scores():
    rows = [row("scifact/1", "m", "supports"), {"item_id": "scifact/2", "model": "m", "error": "timeout"}]
    out = report.model_summary(rows, ITEMS, "m", price=None, bootstrap=50)
    assert out["errors"] == 1 and out["scifact"]["n"] == 1


def test_abstract_enough_share_from_panel_majority_on_originals():
    panel = ["a", "b", "c"]
    rows = ([row("arxiv/p1/original", m, v) for m, v in zip(panel, ["supports", "supports", "not_enough_info"])]
            + [row("arxiv/p2/original", m, v) for m, v in zip(panel, ["not_enough_info"] * 3)]
            + [row("arxiv/p2/swapped", m, "supports") for m in panel])
    assert report.abstract_enough(rows, panel) == {"originals": 2, "decided_from_abstract": 1, "share": 0.5}


def test_recommendation_is_cheapest_model_within_tolerance_of_best():
    summaries = [
        {"model": "best", "cost_per_1000_usd": 9.0, "scifact": {"accuracy": 0.86}},
        {"model": "close_cheap", "cost_per_1000_usd": 2.0, "scifact": {"accuracy": 0.85}},
        {"model": "cheapest_bad", "cost_per_1000_usd": 0.1, "scifact": {"accuracy": 0.70}},
    ]
    rec = report.recommendation(summaries, tolerance=0.02)
    assert rec == {"model": "close_cheap", "best_model": "best", "accuracy": 0.85, "best_accuracy": 0.86,
                   "cost_per_1000_usd": 2.0, "best_cost_per_1000_usd": 9.0, "tolerance": 0.02,
                   "dataset": "scifact"}


def test_refusals_count_as_failed_checks_and_are_reported_separately():
    rows = [row("scifact/1", "m", "supports"),
            {"item_id": "scifact/2", "model": "m", "refused": '{"category": "bio"}'}]
    out = report.model_summary(rows, ITEMS, "m", price=None, bootstrap=50)
    assert out["refusals"] == 1 and out["refusals_by_dataset"] == {"scifact": 1}
    assert out["scifact"]["n"] == 2                     # the refused item still counts
    assert out["scifact"]["accuracy"] == 0.5            # ...as a failed check
    assert out["scifact"]["answered_accuracy"] == 1.0   # accuracy on the items it did answer
    assert out["errors"] == 0


def test_recommendation_can_be_computed_per_dataset():
    summaries = [
        {"model": "a", "cost_per_1000_usd": 9.0, "scifact": {"accuracy": 0.90}, "arxiv": {"accuracy": 0.80}},
        {"model": "b", "cost_per_1000_usd": 1.0, "scifact": {"accuracy": 0.80}, "arxiv": {"accuracy": 0.89}},
    ]
    assert report.recommendation(summaries, dataset="scifact")["model"] == "a"
    assert report.recommendation(summaries, dataset="arxiv")["model"] == "b"
    assert report.recommendation(summaries, dataset="arxiv")["dataset"] == "arxiv"


def test_intervals_overlap():
    assert report.intervals_overlap([0.83, 0.907], [0.85, 0.92]) is True
    assert report.intervals_overlap([0.70, 0.79], [0.80, 0.90]) is False


def test_error_profile_counts_misses_and_false_alarms_with_refusals_as_flags():
    items = {
        "scifact/s1": {"id": "scifact/s1", "dataset": "scifact", "label": "supports"},
        "scifact/s2": {"id": "scifact/s2", "dataset": "scifact", "label": "supports"},
        "scifact/c1": {"id": "scifact/c1", "dataset": "scifact", "label": "contradicts"},
        "scifact/n1": {"id": "scifact/n1", "dataset": "scifact", "label": "not_enough_info"},
    }
    rows = [row("scifact/s1", "m", "not_enough_info"),                   # false alarm
            {"item_id": "scifact/s2", "model": "m", "refused": "{}"},     # refusal -> needs a human -> flag
            row("scifact/c1", "m", "supports"),                           # missed
            row("scifact/n1", "m", "not_enough_info")]                    # correctly flagged
    p = report.error_profile(rows, items, "m", "scifact")
    assert p == {"correct_citations": 2, "false_alarms": 2, "false_alarm_rate": 1.0,
                 "wrong_citations": 2, "missed": 1, "miss_rate": 0.5}


def test_hard_cases_are_items_most_models_got_wrong():
    items = {i: {"id": i, "dataset": "arxiv", "label": "supports", "claim": i, "cited_title": "T",
                 "paper_id": "p", "cited_arxiv_id": "c"} for i in ("arxiv/a/original", "arxiv/b/original")}
    rows = ([row("arxiv/a/original", m, "not_enough_info") for m in ("m1", "m2", "m3")]
            + [row("arxiv/b/original", m, v) for m, v in (("m1", "supports"), ("m2", "supports"), ("m3", "contradicts"))])
    for r in rows:
        r["rationale"] = "because"
    hard = report.hard_cases(rows, items, ["m1", "m2", "m3"], min_wrong=2)
    assert [h["item_id"] for h in hard] == ["arxiv/a/original"]
    assert hard[0]["wrong"] == 3 and hard[0]["verdicts"]["m1"] == {"verdict": "not_enough_info", "correct": False,
                                                                     "rationale": "because"}


def test_cost_per_paper_adds_editor_time_for_every_flag_on_a_correct_citation():
    # 10 citations/paper, 20% false alarms -> 2 flags; 3 min each at $40/h -> $4.00; model $0.02/paper
    out = report.cost_per_paper(model_usd=0.02, false_alarm_rate=0.2, citations_per_paper=10,
                                minutes_per_flag=3, editor_usd_per_hour=40)
    assert out == {"model_usd": 0.02, "false_alarms": 2.0, "editor_minutes": 6.0, "editor_usd": 4.0,
                   "total_usd": 4.02}


def test_break_even_minutes_per_flag():
    # pricier model: $0.05/paper, 2 false alarms/paper; cheap model: $0.02/paper, 5 false alarms/paper.
    # It pays off once 3 extra flags cost more than $0.03 of editor time: 3 * m/60 * $40 = 0.03 -> m = 0.015 min
    m = report.break_even_minutes(pricier_usd=0.05, pricier_false_alarms=2, cheaper_usd=0.02, cheaper_false_alarms=5,
                                  editor_usd_per_hour=40)
    assert abs(m - 0.015) < 1e-9
    # if the pricier model also raises more false alarms, it never pays off
    assert report.break_even_minutes(0.05, 6, 0.02, 5, 40) is None


def test_scifact_confusions_are_counted_and_sorted():
    rows = [row("scifact/1", "a", "contradicts"), row("scifact/1", "b", "contradicts"),
            row("scifact/2", "a", "supports"), row("scifact/1", "c", "supports")]
    assert report.confusions(rows, ITEMS, "scifact") == [
        {"gold": "supports", "predicted": "contradicts", "count": 2},
        {"gold": "contradicts", "predicted": "supports", "count": 1}]
