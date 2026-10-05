"""Aggregate verdict rows into the numbers the data story shows."""

from collections import Counter, defaultdict

from . import judge, metrics

SCIFACT_LABELS = ["supports", "contradicts", "not_enough_info"]


def _binary(verdict: str) -> str:
    return "supports" if judge.is_supported(verdict) else "not_supported"


REFUSED = "__refused__"  # never equals a gold label, so a refusal scores as a failed check


def model_summary(rows: list[dict], items: dict[str, dict], model: str, price: dict | None,
                  bootstrap: int = 2000) -> dict:
    mine = [r for r in rows if r["model"] == model]
    ok = [r for r in mine if "verdict" in r]
    refused = [r for r in mine if "refused" in r]
    out = {"model": model, "errors": len(mine) - len(ok) - len(refused), "calls": len(ok),
           "refusals": len(refused), "refusals_by_dataset": {}}
    for dataset in ("scifact", "arxiv"):
        in_ds = lambda r: items.get(r["item_id"], {}).get("dataset") == dataset
        scored, refused_ds = [r for r in ok if in_ds(r)], [r for r in refused if in_ds(r)]
        if not scored and not refused_ds:
            continue
        if refused_ds:
            out["refusals_by_dataset"][dataset] = len(refused_ds)
        convert = (lambda v: v) if dataset == "scifact" else _binary
        gold_answered = [items[r["item_id"]]["label"] for r in scored]
        pred_answered = [convert(r["verdict"]) for r in scored]
        gold = gold_answered + [items[r["item_id"]]["label"] for r in refused_ds]
        pred = pred_answered + [REFUSED] * len(refused_ds)
        stats = {"n": len(gold), "accuracy": metrics.accuracy(gold, pred),
                 "accuracy_ci": metrics.bootstrap_ci(gold, pred, metrics.accuracy, n=bootstrap),
                 "answered_accuracy": metrics.accuracy(gold_answered, pred_answered) if scored else None}
        if dataset == "scifact":
            stats["macro_f1"] = metrics.macro_f1(gold, pred, SCIFACT_LABELS)
        out[dataset] = stats
    out["cost_per_1000_usd"] = metrics.cost_per_1000(ok, price) if ok else None
    return out


def abstract_enough(rows: list[dict], panel: list[str]) -> dict:
    """Share of real (original) citations where the panel majority reached supports/contradicts from the abstract."""
    votes = defaultdict(list)
    for r in rows:
        if r["item_id"].endswith("/original") and r["model"] in panel and "verdict" in r:
            votes[r["item_id"]].append(r["verdict"])
    complete = [v for v in votes.values() if len(v) == len(panel)]
    decided = sum(Counter(v).most_common(1)[0][0] != "not_enough_info" and
                  Counter(v)["not_enough_info"] < len(panel) / 2 for v in complete)
    return {"originals": len(complete), "decided_from_abstract": decided,
            "share": decided / len(complete) if complete else None}


def recommendation(summaries: list[dict], tolerance: float = 0.02, dataset: str = "scifact") -> dict:
    """Cheapest model whose accuracy on `dataset` is within `tolerance` of the most accurate model."""
    scored = [s for s in summaries if s.get(dataset) and s.get("cost_per_1000_usd") is not None]
    best = max(scored, key=lambda s: (s[dataset]["accuracy"], -s["cost_per_1000_usd"]))
    near = [s for s in scored if s[dataset]["accuracy"] >= best[dataset]["accuracy"] - tolerance - 1e-12]
    pick = min(near, key=lambda s: s["cost_per_1000_usd"])
    return {"model": pick["model"], "best_model": best["model"], "accuracy": pick[dataset]["accuracy"],
            "best_accuracy": best[dataset]["accuracy"], "cost_per_1000_usd": pick["cost_per_1000_usd"],
            "best_cost_per_1000_usd": best["cost_per_1000_usd"], "tolerance": tolerance, "dataset": dataset}


def intervals_overlap(a: list[float], b: list[float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _is_correct(item: dict, verdict: str) -> bool:
    if item["dataset"] == "scifact":
        return verdict == item["label"]
    return _binary(verdict) == item["label"]


def error_profile(rows: list[dict], items: dict[str, dict], model: str, dataset: str) -> dict:
    """As a screening tool: a citation is 'flagged' unless the model says it is supported.
    A refusal also needs a human, so it counts as a flag. A false alarm is a flag on a citation
    whose gold label is 'supports'; a miss is 'supports' on a citation whose gold label is not."""
    correct = wrong = false_alarms = missed = 0
    for r in rows:
        item = items.get(r["item_id"])
        if r["model"] != model or item is None or item["dataset"] != dataset or not ("verdict" in r or "refused" in r):
            continue
        flagged = "refused" in r or r["verdict"] != "supports"
        if item["label"] == "supports":
            correct += 1
            false_alarms += flagged
        else:
            wrong += 1
            missed += not flagged
    return {"correct_citations": correct, "false_alarms": false_alarms,
            "false_alarm_rate": false_alarms / correct if correct else None,
            "wrong_citations": wrong, "missed": missed, "miss_rate": missed / wrong if wrong else None}


def hard_cases(rows: list[dict], items: dict[str, dict], models: list[str], min_wrong: int) -> list[dict]:
    """Items at least `min_wrong` models got wrong, most-missed first."""
    table: dict[str, dict] = {}
    for r in rows:
        if r["model"] in models and "verdict" in r and r["item_id"] in items:
            item = items[r["item_id"]]
            table.setdefault(r["item_id"], {})[r["model"]] = {
                "verdict": r["verdict"], "correct": _is_correct(item, r["verdict"]), "rationale": r.get("rationale", "")}
    out = []
    for item_id, verdicts in table.items():
        wrong = sum(not v["correct"] for v in verdicts.values())
        if wrong >= min_wrong:
            item = items[item_id]
            out.append({"item_id": item_id, "dataset": item["dataset"], "label": item["label"], "claim": item["claim"],
                        "cited_title": item["cited_title"], "paper_id": item.get("paper_id"),
                        "cited_arxiv_id": item.get("cited_arxiv_id"), "wrong": wrong,
                        "verdicts": {m: verdicts[m] for m in models if m in verdicts}})
    return sorted(out, key=lambda h: (-h["wrong"], h["item_id"]))


def cost_per_paper(model_usd: float, false_alarm_rate: float, citations_per_paper: float,
                   minutes_per_flag: float, editor_usd_per_hour: float) -> dict:
    false_alarms = false_alarm_rate * citations_per_paper
    minutes = false_alarms * minutes_per_flag
    editor_usd = minutes / 60 * editor_usd_per_hour
    return {"model_usd": model_usd, "false_alarms": round(false_alarms, 6), "editor_minutes": round(minutes, 6),
            "editor_usd": round(editor_usd, 6), "total_usd": round(model_usd + editor_usd, 6)}


def break_even_minutes(pricier_usd: float, pricier_false_alarms: float, cheaper_usd: float,
                       cheaper_false_alarms: float, editor_usd_per_hour: float) -> float | None:
    """Minutes per false alarm above which the pricier model's lower false-alarm count makes it cheaper overall."""
    saved_flags = cheaper_false_alarms - pricier_false_alarms
    if saved_flags <= 0:
        return None
    return (pricier_usd - cheaper_usd) / (saved_flags * editor_usd_per_hour / 60)


def confusions(rows: list[dict], items: dict[str, dict], dataset: str) -> list[dict]:
    """(gold, predicted) mistake counts over all models, most frequent first."""
    counts = Counter((items[r["item_id"]]["label"], r["verdict"]) for r in rows
                     if "verdict" in r and items.get(r["item_id"], {}).get("dataset") == dataset
                     and r["verdict"] != items[r["item_id"]]["label"])
    return [{"gold": g, "predicted": p, "count": n} for (g, p), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
