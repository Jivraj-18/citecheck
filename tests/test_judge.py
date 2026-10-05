from citecheck import judge

ITEM = {"id": "x", "claim": "EWC reduces forgetting [CITATION].", "cited_title": "Overcoming forgetting",
        "cited_abstract": "We propose EWC, which reduces forgetting.", "label": "supports"}


def test_messages_put_fixed_instructions_first_and_item_last():
    messages = judge.messages(ITEM)
    assert messages[0]["role"] == "system" and messages[0]["content"] == judge.SYSTEM
    assert "EWC reduces forgetting [CITATION]." in messages[1]["content"]
    assert "We propose EWC" in messages[1]["content"]
    # the fixed system text must not vary per item (provider prompt caching)
    assert judge.messages({**ITEM, "claim": "Other."})[0] == messages[0]


def test_schema_is_strict_with_three_verdicts():
    schema = judge.SCHEMA
    assert schema["properties"]["verdict"]["enum"] == ["supports", "contradicts", "not_enough_info"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"verdict", "confidence", "rationale"}


def test_binary_collapse_for_arxiv_scoring():
    assert judge.is_supported("supports") is True
    assert judge.is_supported("contradicts") is False
    assert judge.is_supported("not_enough_info") is False


def test_source_window_finds_the_occurrence_matching_the_claim():
    tex = ("Intro text cites \\cite{ewc} for something unrelated about robots and arms. " + "filler " * 80 +
           "Elastic weight consolidation reduces catastrophic forgetting \\citep{ewc}. More text.")
    window = judge.source_window(tex, "ewc", "Elastic weight consolidation reduces catastrophic forgetting [CITATION].")
    assert "Elastic weight consolidation reduces catastrophic forgetting \\citep{ewc}" in window
    assert "robots and arms" not in window


def test_source_window_none_when_key_absent():
    assert judge.source_window("no citations here", "ewc", "Some claim [CITATION].") is None


def test_source_window_reaches_the_end_of_a_long_sentence():
    # Regression: the 120-character tail cut real sentences short, so the checker flagged them as unfaithful.
    tail = "and then continues with many more words to the end of a long sentence. " * 3
    tex = "A claim \\cite{k} " + tail
    window = judge.source_window(tex, "k", "A claim [CITATION] " + tail)
    assert window.endswith(tail.strip()[-40:]) or tail.strip() in window
