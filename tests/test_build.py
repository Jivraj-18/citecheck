from citecheck import build

REFS = {
    "a": {"key": "a", "title": "Paper A", "raw": "A raw"},
    "b": {"key": "b", "title": "Paper B", "raw": "B raw"},
    "c": {"key": "c", "title": "Paper C", "raw": "C raw"},
    "dup": {"key": "dup", "title": "Paper A again", "raw": "dup raw"},
}
RESOLVED = {
    "a": {"arxiv_id": "1111.0001", "title": "Paper A", "abstract": "About A.", "authors": ["Ann A"]},
    "b": {"arxiv_id": "2222.0002", "title": "Paper B", "abstract": "About B.", "authors": ["Bob B"]},
    "dup": {"arxiv_id": "1111.0001", "title": "Paper A", "abstract": "About A."},  # same paper, other key
    "c": None,  # unresolvable
}


class FakeResolver:
    def __init__(self):
        self.calls = []

    def __call__(self, ref):
        self.calls.append(ref["key"])
        return RESOLVED[ref["key"]]


def test_builds_one_original_and_one_swapped_item_from_different_papers():
    pairs = [{"claim": "Claim about A [CITATION].", "key": "a"}]
    result = build.select_pair("2609.00001", pairs, REFS, FakeResolver(), seed=0)
    original, swapped = result["items"]
    assert original["label"] == "supports" and original["cited_arxiv_id"] == "1111.0001"
    assert swapped["label"] == "not_supported" and swapped["cited_arxiv_id"] == "2222.0002"
    assert original["claim"] == swapped["claim"] == "Claim about A [CITATION]."
    assert swapped["cited_abstract"] == "About B."
    assert original["cited_authors"] == ["Ann A"] and swapped["cited_authors"] == ["Bob B"]
    assert {original["id"], swapped["id"]} == {"arxiv/2609.00001/original", "arxiv/2609.00001/swapped"}


def test_swap_never_reuses_the_same_paper_under_another_key():
    pairs = [{"claim": "Claim about A [CITATION].", "key": "a"}]
    refs = {k: REFS[k] for k in ("a", "dup")}
    result = build.select_pair("p", pairs, refs, FakeResolver(), seed=0)
    assert result["items"] == [] and result["drop_reason"] == "no_swap_candidate"


def test_unresolvable_claims_are_skipped_and_attempts_are_capped():
    pairs = [{"claim": f"Claim {i} [CITATION].", "key": "c"} for i in range(20)]
    resolver = FakeResolver()
    result = build.select_pair("p", pairs, {"c": REFS["c"]}, resolver, seed=0, max_attempts=5)
    assert result["drop_reason"] == "no_resolvable_claim"
    assert len(resolver.calls) <= 5


def test_no_pairs_is_reported():
    assert build.select_pair("p", [], REFS, FakeResolver(), seed=0)["drop_reason"] == "no_citation_pairs"


def test_selection_is_deterministic_for_a_seed():
    pairs = [{"claim": f"Claim {i} about A [CITATION].", "key": "a"} for i in range(10)]
    first = build.select_pair("p", pairs, REFS, FakeResolver(), seed=3)
    second = build.select_pair("p", pairs, REFS, FakeResolver(), seed=3)
    assert first["items"] == second["items"]


def test_titleless_refs_are_skipped_without_a_lookup_and_arxiv_ids_go_first():
    refs = {
        "notitle": {"key": "notitle", "title": "", "arxiv_id": None, "raw": "x"},
        "titled": {"key": "titled", "title": "Paper B", "arxiv_id": None, "raw": "y"},
        "withid": {"key": "withid", "title": "Paper A", "arxiv_id": "1111.0001", "raw": "z"},
    }
    resolved = {"titled": {"arxiv_id": "2222.0002", "title": "Paper B", "abstract": "B.", "authors": []},
                "withid": {"arxiv_id": "1111.0001", "title": "Paper A", "abstract": "A.", "authors": []}}
    calls = []

    def resolver(ref):
        calls.append(ref["key"])
        return resolved.get(ref["key"])

    pairs = [{"claim": "Claim one [CITATION].", "key": "notitle"},
             {"claim": "Claim two [CITATION].", "key": "titled"},
             {"claim": "Claim three [CITATION].", "key": "withid"}]
    result = build.select_pair("p", pairs, refs, resolver, seed=0)
    assert "notitle" not in calls
    assert calls[0] == "withid"
    assert result["items"][0]["claim"] == "Claim three [CITATION]."


def test_interleave_alternates_categories_so_both_are_represented():
    papers = [{"arxiv_id": f"lg{i}", "category": "cs.LG"} for i in range(3)] + \
             [{"arxiv_id": f"cl{i}", "category": "cs.CL"} for i in range(2)]
    assert [p["arxiv_id"] for p in build.interleave(papers, key="category")] == ["lg0", "cl0", "lg1", "cl1", "lg2"]
