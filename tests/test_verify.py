from citecheck import verify

PANEL = ["m1", "m2", "m3"]


def rows(item_id, verdicts):
    return [{"item_id": item_id, "model": m, "verdict": v} for m, v in zip(PANEL, verdicts)]


def test_flags_originals_where_at_least_two_panel_models_say_not_supported():
    verdicts = (rows("arxiv/p1/original", ["supports", "not_enough_info", "contradicts"])
                + rows("arxiv/p2/original", ["supports", "supports", "not_enough_info"])
                + rows("arxiv/p3/original", ["not_enough_info", "not_enough_info", "not_enough_info"]))
    assert verify.flag_originals(verdicts, PANEL) == ["arxiv/p1/original", "arxiv/p3/original"]


def test_missing_panel_verdict_never_counts_toward_a_flag():
    verdicts = rows("arxiv/p1/original", ["not_enough_info", "supports"])  # m3 missing
    assert verify.flag_originals(verdicts, PANEL) == []


def test_swapped_pairs_all_panel_models_call_supported_are_possible_label_noise():
    verdicts = (rows("arxiv/p1/swapped", ["supports", "supports", "supports"])
                + rows("arxiv/p2/swapped", ["supports", "supports", "not_enough_info"]))
    assert verify.possible_label_noise(verdicts, PANEL) == ["arxiv/p1/swapped"]


def test_fleiss_kappa_perfect_and_chance_agreement():
    perfect = [["a", "a", "a"], ["b", "b", "b"], ["a", "a", "a"], ["b", "b", "b"]]
    assert verify.fleiss_kappa(perfect) == 1.0
    # every item split the same way -> agreement no better than chance
    split = [["a", "a", "b"], ["a", "b", "b"], ["a", "a", "b"], ["a", "b", "b"]]
    assert verify.fleiss_kappa(split) < 0


def test_pdf_messages_for_anthropic_use_a_document_block_before_the_text():
    messages = verify.pdf_messages({"claim": "X improves Y [CITATION].", "cited_title": "T"}, b"%PDF-1.4 fake",
                                   route="anthropic")
    user = messages[1]["content"]
    assert user[0]["type"] == "document"
    assert user[0]["source"]["type"] == "base64" and user[0]["source"]["media_type"] == "application/pdf"
    assert user[1]["type"] == "text" and "X improves Y [CITATION]." in user[1]["text"]


def test_pdf_messages_for_gemini_use_an_inline_data_url():
    # Regression: the gateway's Gemini route rejects "file" parts ("Invalid content part type: file")
    # but reads a PDF sent as an image_url data URL.
    messages = verify.pdf_messages({"claim": "X improves Y [CITATION].", "cited_title": "T"}, b"%PDF-1.4 fake",
                                   route="gemini")
    part = messages[1]["content"][1]
    assert part["type"] == "image_url" and part["image_url"]["url"].startswith("data:application/pdf;base64,")


def test_pdf_messages_for_openrouter_attach_a_file_part():
    messages = verify.pdf_messages({"claim": "X improves Y [CITATION].", "cited_title": "T"}, b"%PDF-1.4 fake",
                                   route="openrouter")
    user = messages[1]["content"]
    assert messages[0]["content"] == verify.PDF_SYSTEM
    assert any(part["type"] == "file" and part["file"]["file_data"].startswith("data:application/pdf;base64,")
               for part in user)
    assert any(part["type"] == "text" and "X improves Y [CITATION]." in part["text"] for part in user)


def test_classification_schema_and_messages_for_confirmed_cases():
    assert verify.CATEGORIES == ["specific_claim_unsupported", "conventional_or_background", "describes_citing_work"]
    assert verify.CLASSIFY_SCHEMA["properties"]["category"]["enum"] == verify.CATEGORIES
    item = {"claim": "Mousetrap [CITATION] is an attack.", "cited_title": "H-CoT"}
    reads = {"a": {"verdict": "not_enough_info", "rationale": "Never mentions Mousetrap."}}
    messages = verify.classify_messages(item, reads)
    assert messages[0]["content"] == verify.CLASSIFY_SYSTEM
    assert "Mousetrap [CITATION] is an attack." in messages[1]["content"]
    assert "Never mentions Mousetrap." in messages[1]["content"]


def test_publishable_keeps_only_specific_unsupported_claims_in_order():
    cats = {"x": "conventional_or_background", "y": "specific_claim_unsupported", "z": "specific_claim_unsupported"}
    assert verify.publishable(["x", "y", "z"], cats, limit=1) == ["y"]
