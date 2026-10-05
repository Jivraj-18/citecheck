"""Step 7: verify the presumed-correct original arXiv citations.

The panel (3 models from different families) reuses its main-run verdicts.
Originals that at least 2 of 3 say are not supported get a full-PDF read of
the cited paper. Swapped pairs that all 3 say ARE supported are reported as
possible label noise (the swapped-in paper may support the claim too).
"""

import base64
from collections import Counter, defaultdict

PDF_SYSTEM = """You check a citation against the full text of the cited paper.

You get a sentence from a citing paper, in which one citation has been replaced by [CITATION], and the PDF of the paper that [CITATION] refers to. Read the cited paper and decide whether it supports what the sentence attributes to it.

Verdicts:
- supports: the cited paper supports the part of the sentence attributed to the citation (including when the sentence names it as the source of a method, dataset, model, or result it presents).
- contradicts: the cited paper states something incompatible with what the sentence attributes to it.
- not_enough_info: the cited paper neither supports nor contradicts it.

Judge only what the sentence attributes to the citation. Quote the most relevant passage verbatim (or an empty string if none), give its page number (0 if none), your confidence (0 to 1), and a two or three sentence rationale."""

PDF_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supports", "contradicts", "not_enough_info"]},
        "quote": {"type": "string"},
        "page": {"type": "integer"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "quote", "page", "confidence", "rationale"],
    "additionalProperties": False,
}


def _by_item(verdicts: list[dict], panel: list[str], kind: str) -> dict[str, dict[str, str]]:
    table = defaultdict(dict)
    for row in verdicts:
        if row["item_id"].endswith(f"/{kind}") and row["model"] in panel and "verdict" in row:
            table[row["item_id"]][row["model"]] = row["verdict"]
    return table


def flag_originals(verdicts: list[dict], panel: list[str], min_votes: int = 2) -> list[str]:
    table = _by_item(verdicts, panel, "original")
    return sorted(item for item, votes in table.items()
                  if len(votes) == len(panel) and sum(v != "supports" for v in votes.values()) >= min_votes)


def possible_label_noise(verdicts: list[dict], panel: list[str]) -> list[str]:
    table = _by_item(verdicts, panel, "swapped")
    return sorted(item for item, votes in table.items()
                  if len(votes) == len(panel) and all(v == "supports" for v in votes.values()))


def fleiss_kappa(ratings: list[list[str]]) -> float:
    """Ratings: one list per item, one label per rater (same number of raters per item)."""
    n = len(ratings[0])
    categories = sorted({label for item in ratings for label in item})
    counts = [Counter(item) for item in ratings]
    p_items = [(sum(c[k] ** 2 for k in categories) - n) / (n * (n - 1)) for c in counts]
    p_bar = sum(p_items) / len(ratings)
    p_cat = [sum(c[k] for c in counts) / (len(ratings) * n) for k in categories]
    p_e = sum(p ** 2 for p in p_cat)
    return 1.0 if p_e == 1 else (p_bar - p_e) / (1 - p_e)


def pdf_messages(item: dict, pdf_bytes: bytes, route: str) -> list[dict]:
    data = base64.b64encode(pdf_bytes).decode()
    text = {"type": "text", "text": f"Sentence: {item['claim']}\n\nCited paper title: {item['cited_title']}"}
    if route == "anthropic":  # document block, placed before the text
        pdf = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
        content = [pdf, text]
    elif route == "gemini":  # the Gemini OpenAI-compatible route takes PDFs as an image_url data URL
        content = [text, {"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{data}"}}]
    else:  # OpenRouter: file part
        content = [text, {"type": "file",
                          "file": {"filename": "cited.pdf", "file_data": f"data:application/pdf;base64,{data}"}}]
    return [{"role": "system", "content": PDF_SYSTEM}, {"role": "user", "content": content}]


# ---------------------------------------------------------------- classifying confirmed cases

CATEGORIES = ["specific_claim_unsupported", "conventional_or_background", "describes_citing_work"]

CLASSIFY_SYSTEM = """Two models read the full text of a cited paper and judged that it does not support what a citing sentence attributes to it. Classify the case:

- specific_claim_unsupported: the sentence attributes a specific finding, number, method, property, or description to the cited paper, and the paper does not contain it (including when a different paper was probably meant).
- conventional_or_background: the citation is a conventional pointer (e.g. citing a model family's main paper for a later version, or a related paper for a general background statement); not a real error.
- describes_citing_work: the sentence mainly describes what the citing authors do or how they use the cited work, which the cited paper cannot be expected to state.

Give a one-sentence reason."""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"category": {"type": "string", "enum": CATEGORIES}, "reason": {"type": "string"}},
    "required": ["category", "reason"],
    "additionalProperties": False,
}


def classify_messages(item: dict, reads: dict) -> list[dict]:
    notes = "\n".join(f"- Reader {i + 1}: {r.get('verdict')}. {r.get('rationale', '')}" for i, r in enumerate(reads.values()))
    user = (f"Sentence: {item['claim']}\n\nCited paper: {item['cited_title']}\n\n"
            f"What the full-text readers found:\n{notes}")
    return [{"role": "system", "content": CLASSIFY_SYSTEM}, {"role": "user", "content": user}]


def publishable(item_ids: list[str], categories: dict[str, str], limit: int = 5) -> list[str]:
    return [i for i in item_ids if categories.get(i) == "specific_claim_unsupported"][:limit]
