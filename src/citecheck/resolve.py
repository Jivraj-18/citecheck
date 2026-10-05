"""Resolve a bibliography entry to a real paper with an abstract.

Order: arXiv id in the entry → arXiv exact-title search (free; ML papers are
mostly on arXiv even when the .bib has no id). A title match is accepted only
when it is unambiguous: same normalized title, and if several papers share
the title, author surnames (then year) must single one out. Otherwise the
reference is left unresolved rather than guessed.
"""

import re
import unicodedata
from difflib import SequenceMatcher

from . import arxiv

TITLE_THRESHOLD = 0.92


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def normalize_title(title: str) -> str:
    title = _ascii(title).lower().replace("{", "").replace("}", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title).split())


def surnames(authors: str) -> list[str]:
    authors = _ascii(authors).replace("{", "").replace("}", "")
    authors = re.sub(r"\b(and\s+)?(others|et al\.?)", "", authors).strip(" ,")
    if not authors:
        return []
    segments = [s.strip() for s in re.split(r"\s+and\s+", authors) if s.strip()]
    if all("," in s for s in segments):  # BibTeX "Last, First and Last, First"
        names = [s.split(",")[0] for s in segments]
    else:  # "First Last, First Last, and First Last"
        names = [s for s in re.split(r",\s*(?:and\s+)?|\s+and\s+", authors) if s.strip()]
        names = [n.split()[-1] for n in names]
    return [re.sub(r"[^a-z\-]", "", n.lower()) for n in names if re.sub(r"[^a-z]", "", n.lower())]


def _year(entry: dict) -> int | None:
    match = re.match(r"(\d{4})", entry.get("published", ""))
    return int(match.group(1)) if match else None


def choose_match(ref: dict, candidates: list[dict]) -> dict | None:
    want = normalize_title(ref.get("title", ""))
    if not want:
        return None
    close = [c for c in candidates
             if SequenceMatcher(None, want, normalize_title(c["title"])).ratio() >= TITLE_THRESHOLD]
    ref_surnames = set(surnames(ref.get("authors", "")))
    if ref_surnames:
        by_author = [c for c in close if ref_surnames & {surnames(a)[-1] for a in c["authors"] if surnames(a)}]
        close = by_author
    year = re.search(r"\d{4}", ref.get("year", "") or "")
    if len(close) > 1 and year:
        target = int(year.group(0))
        best = min(abs((_year(c) or 0) - target) for c in close)
        close = [c for c in close if abs((_year(c) or 0) - target) == best and best <= 1]
    return close[0] if len(close) == 1 else None


def resolve(ref: dict) -> dict | None:
    """Returns {"arxiv_id", "title", "authors", "abstract", "published", "method"} or None."""
    if ref.get("arxiv_id"):
        entry = arxiv.metadata([ref["arxiv_id"]]).get(ref["arxiv_id"])
        if entry:
            return {**entry, "method": "arxiv_id"}
    if ref.get("title"):
        entry = choose_match(ref, arxiv.search_title(ref["title"]))
        if entry:
            return {**entry, "method": "arxiv_title"}
    return None
