from citecheck import resolve

EWC_2017 = {"arxiv_id": "1612.00796", "title": "Overcoming catastrophic forgetting in neural networks",
            "authors": ["James Kirkpatrick", "Razvan Pascanu"], "published": "2016-12-02T19:20:00Z"}
EWC_2025 = {"arxiv_id": "2507.10485", "title": "Overcoming catastrophic forgetting in neural networks",
            "authors": ["Brandon Loke", "Filippo Quadri"], "published": "2025-07-14T10:00:00Z"}
OTHER = {"arxiv_id": "1904.00001", "title": "Overcoming forgetting in deep networks with replay",
         "authors": ["A. Person"], "published": "2019-04-01T00:00:00Z"}


def test_normalize_title_ignores_case_punctuation_and_latex_leftovers():
    assert resolve.normalize_title("FastTree: Optimizing  Attention-Kernel {and} Runtime.") == \
        "fasttree optimizing attention kernel and runtime"


def test_surnames_from_bib_and_bbl_author_strings():
    assert resolve.surnames("Kirkpatrick, James and Pascanu, Razvan and others") == ["kirkpatrick", "pascanu"]
    assert resolve.surnames("James Kirkpatrick, Razvan Pascanu, and Neil Rabinowitz") == \
        ["kirkpatrick", "pascanu", "rabinowitz"]
    assert resolve.surnames("") == []


def test_choose_match_uses_authors_to_pick_between_identical_titles():
    ref = {"title": "Overcoming catastrophic forgetting in neural networks",
           "authors": "Kirkpatrick, James and Pascanu, Razvan", "year": "2017"}
    assert resolve.choose_match(ref, [EWC_2025, EWC_2017, OTHER])["arxiv_id"] == "1612.00796"


def test_choose_match_rejects_different_titles_and_ambiguous_ties():
    ref = {"title": "Overcoming catastrophic forgetting in neural networks", "authors": "", "year": ""}
    # identical titles, no author or year to tell them apart -> refuse rather than guess
    assert resolve.choose_match(ref, [EWC_2025, EWC_2017]) is None
    ref2 = {"title": "A completely different paper about graphs", "authors": "Kirkpatrick, J.", "year": "2017"}
    assert resolve.choose_match(ref2, [EWC_2017, OTHER]) is None


def test_choose_match_accepts_single_close_title_without_author_info():
    ref = {"title": "Overcoming catastrophic forgetting in neural networks.", "authors": "", "year": ""}
    assert resolve.choose_match(ref, [EWC_2017, OTHER])["arxiv_id"] == "1612.00796"
