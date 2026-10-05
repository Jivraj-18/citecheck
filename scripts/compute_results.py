"""Step 8: all numbers for the data story → docs/data/results.json.

Every number on the page must come from this file (or models.json /
examples.json), never be typed by hand.
"""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from citecheck import config, latex, metrics, report, verify

rows = [json.loads(line) for line in Path("results/verdicts.jsonl").read_text().splitlines()]
items = {i["id"]: i for name in ("scifact", "arxiv")
         for i in (json.loads(line) for line in Path(f"data/eval/{name}.jsonl").read_text().splitlines())}
models = json.loads(Path("docs/data/models.json").read_text())["models"]
verification = json.loads(Path("results/verification.json").read_text())
dropouts = json.loads(Path("data/eval/arxiv_dropouts.json").read_text())
classification = json.loads(Path("results/classification.json").read_text())
dataprep = json.loads(Path("results/dataprep_checks.json").read_text())

summaries = [report.model_summary(rows, items, m, models[m]["price_per_million"]) for m in config.MODELS]
for s in summaries:
    s["name"] = models[s["model"]]["name"]
    s["price_per_million"] = models[s["model"]]["price_per_million"]

# Pareto frontier on SciFact (human labels): cost per 1,000 checks vs accuracy
points = {s["model"]: (s["cost_per_1000_usd"], s["scifact"]["accuracy"]) for s in summaries if "scifact" in s}
frontier = metrics.pareto_frontier(points)
frontier_arxiv = metrics.pareto_frontier(
    {s["model"]: (s["cost_per_1000_usd"], s["arxiv"]["accuracy"]) for s in summaries if "arxiv" in s})

# a manuscript's cost = cost per check × citations checked per paper (median single-citation sentences)
kept_papers = {i["paper_id"] for i in items.values() if i["dataset"] == "arxiv"}
per_paper = []
for paper_id in sorted(kept_papers):
    files = latex.read_archive(Path("cache/arxiv/src") / paper_id)
    per_paper.append(len(latex.citation_pairs(files)[0]))
citations_per_paper = statistics.median(per_paper)

for s in summaries:  # cost of checking one typical paper's single-citation sentences
    s["cost_per_manuscript_usd"] = s["cost_per_1000_usd"] * citations_per_paper / 1000
by_model = {s["model"]: s for s in summaries}
recommendations = {}
for dataset in ("scifact", "arxiv"):
    rec = report.recommendation(summaries, tolerance=0.02, dataset=dataset)
    rec["name"], rec["best_name"] = by_model[rec["model"]]["name"], by_model[rec["best_model"]]["name"]
    rec["cost_per_manuscript_usd"] = by_model[rec["model"]]["cost_per_manuscript_usd"]
    rec["best_cost_per_manuscript_usd"] = by_model[rec["best_model"]]["cost_per_manuscript_usd"]
    rec["within_margin_of_error"] = report.intervals_overlap(by_model[rec["model"]][dataset]["accuracy_ci"],
                                                             by_model[rec["best_model"]][dataset]["accuracy_ci"])
    recommendations[dataset] = rec
family = lambda model_id: model_id.split("/")[0]
leaders_differ = family(recommendations["scifact"]["best_model"]) != family(recommendations["arxiv"]["best_model"])

# ---- where models fail, and whether paying more saves editor time
ASSUMPTIONS = {"minutes_per_flag": 3, "editor_usd_per_hour": 40,
               "note": "Assumptions, not measurements: how long an editor takes to clear one flagged citation, "
                       "and what an hour of editor time costs. Readers can change both on the page."}
for s_ in summaries:
    s_["error_profile"] = {d: report.error_profile(rows, items, s_["model"], d) for d in ("scifact", "arxiv")}
economics = {}
for dataset in ("scifact", "arxiv"):
    per_model = {s_["model"]: report.cost_per_paper(s_["cost_per_manuscript_usd"],
                                                     s_["error_profile"][dataset]["false_alarm_rate"],
                                                     citations_per_paper, ASSUMPTIONS["minutes_per_flag"],
                                                     ASSUMPTIONS["editor_usd_per_hour"]) for s_ in summaries}
    cheapest = min(summaries, key=lambda s_: s_["cost_per_manuscript_usd"])["model"]
    best_total = min(per_model, key=lambda m: per_model[m]["total_usd"])
    fewest_alarms = min(per_model, key=lambda m: per_model[m]["false_alarms"])
    economics[dataset] = {
        "per_model": per_model, "cheapest_model": cheapest, "best_total_model": best_total,
        "fewest_false_alarms_model": fewest_alarms, "paying_more_saves": best_total != cheapest,
        "break_even_minutes": report.break_even_minutes(
            per_model[fewest_alarms]["model_usd"], per_model[fewest_alarms]["false_alarms"],
            per_model[cheapest]["model_usd"], per_model[cheapest]["false_alarms"], ASSUMPTIONS["editor_usd_per_hour"]),
        "editor_minutes_saved_vs_cheapest": per_model[cheapest]["editor_minutes"] - per_model[best_total]["editor_minutes"],
    }
    fewest_misses = min(summaries, key=lambda s_: (s_["error_profile"][dataset]["miss_rate"],
                                                   s_["error_profile"][dataset]["false_alarm_rate"]))["model"]
    rates = {s_["model"]: s_["error_profile"][dataset] for s_ in summaries}
    economics[dataset].update({
        "fewest_misses_model": fewest_misses,
        "fewest_misses_rate": rates[fewest_misses]["miss_rate"],
        "fewest_misses_false_alarm_rate": rates[fewest_misses]["false_alarm_rate"],
        "best_total_miss_rate": rates[best_total]["miss_rate"],
        "best_total_false_alarm_rate": rates[best_total]["false_alarm_rate"],
        "tradeoff": fewest_misses != best_total
                    and rates[fewest_misses]["miss_rate"] < rates[best_total]["miss_rate"],
    })
    economics[dataset]["break_even_seconds"] = (economics[dataset]["break_even_minutes"] * 60
                                                if economics[dataset]["break_even_minutes"] is not None else None)

hard = report.hard_cases(rows, items, list(config.MODELS), min_wrong=len(config.MODELS))
hard_by_dataset = {d: [h for h in hard if h["dataset"] == d] for d in ("scifact", "arxiv")}
hard_shown = [h for pair in zip(hard_by_dataset["scifact"], hard_by_dataset["arxiv"]) for h in pair][:6]

first, second = config.PDF_READERS
reads = verification["pdf_reads"]
read_ok = {i: r for i, r in reads.items() if "verdict" in r[first]}
overturned = sum(r[first]["verdict"] == "supports" for r in read_ok.values())

results = {
    "generated": datetime.now(timezone.utc).isoformat(),
    "models": summaries,
    "pareto_frontier_scifact": frontier,
    "pareto_frontier_arxiv": frontier_arxiv,
    "recommendation": recommendations,
    "leading_family_differs_by_dataset": leaders_differ,
    "excluded_models": {"openai/gpt-6.1-sol": "no API access during this run",
                        "openai/gpt-6-luna": "no API access during this run",
                        "openai/gpt-6-astra": "cost, $10/$50 per 1M tokens",
                        "anthropic/claude-fable-5.1": "cost, $10/$50 per 1M tokens",
                        "anthropic/claude-opus-5.5": "not included in this run"},
    "datasets": {
        "scifact": {"n": sum(i["dataset"] == "scifact" for i in items.values()),
                    "labels": {k: sum(i["dataset"] == "scifact" and i["label"] == k for i in items.values())
                               for k in report.SCIFACT_LABELS}},
        "arxiv": {"papers": len(kept_papers), "items": sum(i["dataset"] == "arxiv" for i in items.values()),
                  "dropouts": dropouts, "citations_per_paper_median": citations_per_paper,
                  "resolved_by_arxiv_id_share": sum(i.get("resolve_method") == "arxiv_id" for i in items.values()
                                                    if i["dataset"] == "arxiv")
                                                / sum(i["dataset"] == "arxiv" for i in items.values())},
    },
    "abstract_enough": report.abstract_enough(rows, config.PANEL),
    "assumptions": ASSUMPTIONS,
    "economics": economics,
    "miss_rate_range": {d: [min(s_["error_profile"][d]["miss_rate"] for s_ in summaries),
                            max(s_["error_profile"][d]["miss_rate"] for s_ in summaries)] for d in ("scifact", "arxiv")},
    "false_alarms_per_paper_range": {d: [min(v["false_alarms"] for v in economics[d]["per_model"].values()),
                                         max(v["false_alarms"] for v in economics[d]["per_model"].values())]
                                     for d in ("scifact", "arxiv")},
    "false_alarms_per_paper_overall": [min(v["false_alarms"] for e in economics.values() for v in e["per_model"].values()),
                                       max(v["false_alarms"] for e in economics.values() for v in e["per_model"].values())],
    "model_cost_per_paper_range": [min(s_["cost_per_manuscript_usd"] for s_ in summaries),
                                   max(s_["cost_per_manuscript_usd"] for s_ in summaries)],
    "tradeoff_in_both_datasets": all(e["tradeoff"] for e in economics.values()),
    "fewest_false_alarms_wins": all(e["best_total_model"] == e["fewest_false_alarms_model"] for e in economics.values()),
    "scifact_confusions": report.confusions(rows, items, "scifact"),
    "hard_cases": {"all_models_wrong": {d: len(hard_by_dataset[d]) for d in hard_by_dataset},
                   "shown": hard_shown},
    "dataprep_checks": {"checker": dataprep["checker"].split(" ")[0],
                        "extraction_checked": dataprep["extraction"]["checked"],
                        "extraction_faithful": dataprep["extraction"]["faithful"],
                        "citation_position_correct": dataprep["extraction"]["citation_position_correct"],
                        "resolution_checked": dataprep["resolution"]["checked"],
                        "resolution_same_work": dataprep["resolution"]["same_work"]},
    "verification": {
        "panel": config.PANEL, "min_votes": config.PANEL_MIN_VOTES, "pdf_readers": config.PDF_READERS, "fleiss_kappa": verification["fleiss_kappa"],
        "kappa_items": verification["kappa_items"],
        "flagged_originals": len(verification["flagged_originals"]),
        "pdf_read": len(read_ok),
        "full_text_overturned_to_supported": overturned,
        "confirmed_unsupported": len(verification["confirmed_unsupported"]),
        "confirmed_by_category": {c: sum(v["category"] == c for v in classification.values())
                                  for c in [*verify.CATEGORIES, "disagreement"]},
        "possible_label_noise_swapped": len(verification["possible_label_noise_swapped"]),
    },
    "total_spend_usd": sum(json.loads(line).get("cost_usd") or 0
                           for line in Path("cache/llm/ledger.jsonl").read_text().splitlines()),
}
Path("docs/data/results.json").write_text(json.dumps(results, indent=1))

# published examples: only citations two full-text readers from different families both judged not supported
papers = {p["arxiv_id"]: p for p in json.loads(Path("data/papers.json").read_text())}
def reader_confidence(item_id):
    return sum(reads[item_id][m].get("confidence", 0) for m in config.PDF_READERS) / len(config.PDF_READERS)


categories = {i: c["category"] for i, c in classification.items()}
published = verify.publishable(sorted(verification["confirmed_unsupported"], key=reader_confidence, reverse=True),
                               categories, limit=5)
examples = []
for item_id in published:
    item = items[item_id]
    examples.append({
        "item_id": item_id, "claim": item["claim"],
        "citing": {"arxiv_id": item["paper_id"], "title": papers[item["paper_id"]]["title"]},
        "cited": {"arxiv_id": item["cited_arxiv_id"], "title": item["cited_title"]},
        "reads": {m: {k: reads[item_id][m][k] for k in ("verdict", "quote", "page", "rationale")}
                  for m in config.PDF_READERS},
    })
Path("docs/data/examples.json").write_text(json.dumps(examples, indent=1))
print(json.dumps({k: results[k] for k in ("pareto_frontier_scifact", "abstract_enough", "verification")}, indent=1))
