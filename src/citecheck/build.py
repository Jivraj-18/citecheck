"""Build the arXiv eval items: for each paper, one real claim–citation pair
("supports", presumed and later checked by the verification panel) and the
same claim with a different reference from the same paper swapped in
("not_supported", a hard wrong citation labelled by construction).
"""

import random
from typing import Callable


def _item(paper_id: str, kind: str, label: str, pair: dict, ref: dict, resolved: dict) -> dict:
    return {
        "id": f"arxiv/{paper_id}/{kind}",
        "dataset": "arxiv",
        "paper_id": paper_id,
        "claim": pair["claim"],
        "cited_title": resolved["title"],
        "cited_abstract": resolved["abstract"],
        "cited_arxiv_id": resolved["arxiv_id"],
        "cited_authors": resolved.get("authors", []),
        "label": label,
        "ref_key": ref["key"],
        "ref_raw": ref.get("raw", ""),
        "resolve_method": resolved.get("method"),
    }


def select_pair(paper_id: str, pairs: list[dict], refs: dict[str, dict],
                resolver: Callable[[dict], dict | None], seed: int = 0, max_attempts: int = 8) -> dict:
    """Returns {"items": [original, swapped], "drop_reason": None} or {"items": [], "drop_reason": str}."""
    if not pairs:
        return {"items": [], "drop_reason": "no_citation_pairs"}
    rng = random.Random(f"{seed}/{paper_id}")
    resolved, attempts = {}, 0

    def priority(key: str) -> int:  # 0: has arXiv id, 1: has title, 2: nothing to look up
        return 0 if refs[key].get("arxiv_id") else 1 if refs[key].get("title") else 2

    def lookup(key: str) -> dict | None:
        nonlocal attempts
        if priority(key) == 2:
            return None  # no id and no title: nothing to search, don't spend a lookup
        if key not in resolved:
            if attempts >= max_attempts:
                return None
            attempts += 1
            result = resolver(refs[key])
            resolved[key] = result if result and result.get("abstract") else None
        return resolved[key]

    order = pairs[:]
    rng.shuffle(order)
    order.sort(key=lambda p: priority(p["key"]))  # stable: random within each priority
    original = next(((p, lookup(p["key"])) for p in order if lookup(p["key"])), None)
    if original is None:
        return {"items": [], "drop_reason": "no_resolvable_claim"}
    pair, cited = original

    others = [k for k in refs if k != pair["key"]]
    rng.shuffle(others)
    others.sort(key=priority)
    for key in others:
        candidate = lookup(key)
        if candidate and candidate["arxiv_id"] != cited["arxiv_id"]:
            return {"items": [_item(paper_id, "original", "supports", pair, refs[pair["key"]], cited),
                              _item(paper_id, "swapped", "not_supported", pair, refs[key], candidate)],
                    "drop_reason": None}
        if attempts >= max_attempts and key not in resolved:
            break
    return {"items": [], "drop_reason": "no_swap_candidate"}


def interleave(papers: list[dict], key: str) -> list[dict]:
    """Round-robin across groups (in first-seen group order), keeping order within each group."""
    groups: dict[str, list[dict]] = {}
    for paper in papers:
        groups.setdefault(paper[key], []).append(paper)
    out, queues = [], list(groups.values())
    while any(queues):
        for queue in queues:
            if queue:
                out.append(queue.pop(0))
    return out
