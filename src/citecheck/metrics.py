"""Scoring: accuracy, macro-F1, bootstrap confidence intervals, cost, Pareto frontier."""

import random
from typing import Callable, Sequence


def accuracy(gold: Sequence[str], pred: Sequence[str]) -> float:
    return sum(g == p for g, p in zip(gold, pred)) / len(gold)


def macro_f1(gold: Sequence[str], pred: Sequence[str], labels: Sequence[str]) -> float:
    scores = []
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, pred))
        fp = sum(g != label and p == label for g, p in zip(gold, pred))
        fn = sum(g == label and p != label for g, p in zip(gold, pred))
        scores.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return sum(scores) / len(scores)


def bootstrap_ci(gold: Sequence[str], pred: Sequence[str], metric: Callable, n: int = 2000,
                 seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    rng = random.Random(seed)
    indices = range(len(gold))
    values = []
    for _ in range(n):
        sample = [rng.choice(indices) for _ in indices]
        values.append(metric([gold[i] for i in sample], [pred[i] for i in sample]))
    values.sort()
    tail = (1 - level) / 2
    return values[int(tail * n)], values[int((1 - tail) * n) - 1]


def call_cost(record: dict, price: dict | None) -> float:
    if record.get("cost_usd") is not None:
        return record["cost_usd"]
    usage = record.get("usage") or {}
    return (usage.get("prompt_tokens", 0) * price["input"] + usage.get("completion_tokens", 0) * price["output"]) / 1e6


def cost_per_1000(records: list[dict], price: dict | None) -> float:
    return 1000 * sum(call_cost(r, price) for r in records) / len(records)


def pareto_frontier(points: dict[str, tuple[float, float]]) -> list[str]:
    """Names of (cost, accuracy) points not beaten by any cheaper-or-equal, more-or-equally-accurate point."""
    frontier, best_accuracy = [], float("-inf")
    for name, (cost, acc) in sorted(points.items(), key=lambda kv: (kv[1][0], -kv[1][1])):
        if acc > best_accuracy:
            frontier.append(name)
            best_accuracy = acc
    return frontier
