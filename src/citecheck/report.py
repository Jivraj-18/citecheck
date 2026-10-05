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
