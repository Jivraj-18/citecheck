"""Prompts and output schemas.

- Main task (step 6): does the cited paper's abstract support the claim?
- Data-prep checks (steps 3–4): is an extracted claim faithful to the LaTeX
  source, and does a resolved paper match the bibliography entry?

Fixed instructions come first in every prompt and never vary per item, so
providers can cache them.
"""

import re

from .latex import CITE_RE

SYSTEM = """You check citations in scientific papers.

You get a sentence from a paper in which one citation has been replaced by [CITATION], and the title and abstract of the paper that [CITATION] refers to. Decide whether the cited paper, as described by its abstract, supports what the sentence attributes to it.

Verdicts:
- supports: the abstract supports the part of the sentence attributed to the citation (including when the sentence names the cited work as the source of a method, dataset, model, or result that the abstract describes).
- contradicts: the abstract states something incompatible with what the sentence attributes to it.
- not_enough_info: the abstract neither supports nor contradicts it, or the cited paper appears unrelated to the claim.

Judge only what the sentence attributes to the citation, not the rest of the sentence. Give your confidence (0 to 1) and a one or two sentence rationale."""

VERDICTS = ["supports", "contradicts", "not_enough_info"]
SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "confidence", "rationale"],
    "additionalProperties": False,
}


def messages(item: dict) -> list[dict]:
    user = (f"Sentence: {item['claim']}\n\n"
            f"Cited paper title: {item['cited_title']}\n\n"
            f"Cited paper abstract: {item['cited_abstract']}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def is_supported(verdict: str) -> bool:
    return verdict == "supports"


# ---------------------------------------------------------------- data-prep checks

EXTRACTION_SYSTEM = """You verify a text-extraction step. You get a raw LaTeX excerpt from a paper and a sentence that a parser extracted from it, with one citation command replaced by [CITATION]. Answer whether the extracted sentence is a faithful plain-text rendering of a sentence in the excerpt (LaTeX markup removed is fine; words added, dropped, or merged from different sentences is not), and whether [CITATION] stands for the citation command with the given key in that same sentence."""

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {"faithful": {"type": "boolean"}, "citation_position_correct": {"type": "boolean"},
                   "problem": {"type": "string"}},
    "required": ["faithful", "citation_position_correct", "problem"],
    "additionalProperties": False,
}

RESOLUTION_SYSTEM = """You verify a reference-matching step. You get a bibliography entry from a paper and the title and authors of the paper it was matched to. Answer whether they are the same work (a preprint and its published version count as the same work)."""

RESOLUTION_SCHEMA = {
    "type": "object",
    "properties": {"same_work": {"type": "boolean"}, "problem": {"type": "string"}},
    "required": ["same_work", "problem"],
    "additionalProperties": False,
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())}


def source_window(tex: str, key: str, claim: str, before: int = 400, after: int = 600) -> str | None:
    """The raw LaTeX around the citation of `key` whose surroundings best match the claim."""
    claim_words = _words(claim.replace("[CITATION]", ""))
    best, best_score = None, -1
    for match in CITE_RE.finditer(tex):
        if key not in [k.strip() for k in match.group(1).split(",")]:
            continue
        window = tex[max(0, match.start() - before):match.end() + after]
        score = len(claim_words & _words(window))
        if score > best_score:
            best, best_score = window, score
    return best


def extraction_messages(window: str, key: str, claim: str) -> list[dict]:
    return [{"role": "system", "content": EXTRACTION_SYSTEM},
            {"role": "user", "content": f"Citation key: {key}\n\nRaw LaTeX excerpt:\n{window}\n\nExtracted sentence:\n{claim}"}]


def resolution_messages(ref_raw: str, title: str, authors: list[str]) -> list[dict]:
    return [{"role": "system", "content": RESOLUTION_SYSTEM},
            {"role": "user", "content": f"Bibliography entry: {ref_raw}\n\nMatched paper: {title}\nAuthors: {', '.join(authors)}"}]
