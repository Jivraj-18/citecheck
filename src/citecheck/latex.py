"""Extract (claim sentence, cited reference) pairs from an arXiv LaTeX source.

Plain code, no LLM. The pipeline:
1. Read every .tex / .bib / .bbl file from the e-print archive.
2. Parse the bibliography (.bib preferred for structured titles; .bbl as fallback).
3. Strip comments, floats, and math environments from the .tex body, mark each
   citation command, convert the rest to plain text, and split into sentences.
4. Keep sentences that cite exactly one reference.
"""

import gzip
import io
import re
import tarfile
from pathlib import Path

CITE_RE = re.compile(
    r"\\(?:[Cc]ite[a-z]*|[Pp]arencite|[Tt]extcite|[Aa]utocite|[Ff]ootcite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}"
)
ARXIV_ID_RE = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d])")
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,}{\"]+")
DROP_ENVS = ("figure", "figure*", "table", "table*", "algorithm", "algorithmic", "equation", "equation*",
             "align", "align*", "tabular", "lstlisting", "verbatim", "thebibliography", "wrapfigure",
             "tikzpicture", "minted", "comment")
ABBREVIATIONS = ("e.g.", "i.e.", "et al.", "etc.", "vs.", "Fig.", "Eq.", "Sec.", "cf.", "approx.", "resp.", "w.r.t.")
MATH_SYMBOLS = {"times": "×", "cdot": "·", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠",
                "approx": "≈", "pm": "±", "sim": "~", "infty": "∞", "to": "→", "rightarrow": "→",
                "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "eta": "η", "theta": "θ",
                "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "omega": "ω",
                "varepsilon": "ε", "varphi": "φ", "vartheta": "θ", "varrho": "ρ", "varsigma": "ς"}
MATH_RE = re.compile(r"\\(" + "|".join(sorted(MATH_SYMBOLS, key=len, reverse=True)) + r")(?![a-zA-Z])")
CITE_MARK = "\u27e6CITE:{}\u27e7"
CITE_MARK_RE = re.compile("\u27e6CITE:([^\u27e7]*)\u27e7")


# ---------------------------------------------------------------- archive

def read_archive(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.lower().endswith((".tex", ".bib", ".bbl")):
                    files[member.name] = tar.extractfile(member).read().decode("utf-8", errors="replace")
        return files
    except tarfile.ReadError:
        pass
    try:  # a single gzip-compressed .tex file
        text = gzip.decompress(data).decode("utf-8", errors="replace")
    except OSError:
        return {}  # e.g. a PDF-only submission
    return {"main.tex": text} if "\\documentclass" in text or "\\begin{document}" in text else {}


# ---------------------------------------------------------------- helpers

def balanced(text: str, start: int) -> tuple[str, int]:
    """Content of the {...} group whose '{' is at text[start]; returns (content, index after '}')."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "\\":
            continue
        if ch == "{" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif ch == "}" and text[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return text[start + 1:], len(text)


def strip_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", tex)


def latex_to_text(s: str) -> str:
    """Rough LaTeX → text for titles and author lists."""
    s = re.sub(r"\\[a-zA-Z]+\*?\s*", " ", s)
    s = s.replace("{", "").replace("}", "").replace("~", " ").replace("\\", "")
    return " ".join(s.split())


# ---------------------------------------------------------------- bibliography

def parse_bib(text: str) -> dict[str, dict]:
    refs = {}
    text = strip_comments(text)
    for match in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        kind, key = match.group(1).lower(), match.group(2)
        if kind in ("comment", "string", "preamble"):
            continue
        body, _ = balanced(text, text.index("{", match.start()))
        fields = {}
        for field in re.finditer(r"(\w+)\s*=\s*", body):
            name, pos = field.group(1).lower(), field.end()
            if pos >= len(body):
                continue
            if body[pos] == "{":
                value, _ = balanced(body, pos)
            elif body[pos] == '"':
                end = body.find('"', pos + 1)
                value = body[pos + 1:end if end != -1 else len(body)]
            else:
                value = re.match(r"[^,\n]*", body[pos:]).group(0)
            fields.setdefault(name, value.strip())
        blob = " ".join(fields.values())
        arxiv_id = ARXIV_ID_RE.search(fields.get("eprint", "") or blob)
        doi = DOI_RE.search(fields.get("doi", "") or blob)
        refs[key] = {
            "key": key,
            "title": latex_to_text(fields.get("title", "")),
            "authors": latex_to_text(fields.get("author", "")),
            "year": latex_to_text(fields.get("year", "")),
            "venue": latex_to_text(fields.get("journal", "") or fields.get("booktitle", "")),
            "arxiv_id": arxiv_id.group(1) if arxiv_id else None,
            "doi": doi.group(0).rstrip(".") if doi else None,
            "raw": latex_to_text(blob)[:600],
            "source": "bib",
        }
    return refs


def parse_bbl(text: str) -> dict[str, dict]:
    refs = {}
    text = strip_comments(text)
    for chunk in re.split(r"\\bibitem", text)[1:]:
        match = re.match(r"\s*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?\s*\{([^}]+)\}", chunk)
        if not match:
            continue
        key, rest = match.group(1).strip(), chunk[match.end():]
        rest = rest.split("\\end{thebibliography}")[0]
        blocks = [latex_to_text(b) for b in re.split(r"\\newblock", rest)]
        arxiv_id = ARXIV_ID_RE.search(rest)
        doi = DOI_RE.search(rest)
        refs[key] = {
            "key": key,
            "title": blocks[1].rstrip(".") if len(blocks) > 1 else "",
            "authors": blocks[0].rstrip("."),
            "year": (re.search(r"\b(19|20)\d{2}\b", rest) or [""])[0],
            "venue": blocks[2] if len(blocks) > 2 else "",
            "arxiv_id": arxiv_id.group(1) if arxiv_id else None,
            "doi": doi.group(0).rstrip(".") if doi else None,
            "raw": " ".join(blocks)[:600],
            "source": "bbl",
        }
    return refs


def bibliography(files: dict[str, str]) -> dict[str, dict]:
    refs = {}
    for name, text in files.items():
        if name.endswith(".bbl") or (name.endswith(".tex") and "\\bibitem" in text):
            refs.update(parse_bbl(text))
    for name, text in files.items():  # .bib overrides .bbl: structured fields are more reliable
        if name.endswith(".bib"):
            refs.update(parse_bib(text))
    return refs


# ---------------------------------------------------------------- body text

def document_body(files: dict[str, str]) -> str:
    parts = []
    for name, text in files.items():
        if not name.endswith(".tex"):
            continue
        text = strip_comments(text)
        if "\\begin{document}" in text:
            text = text.split("\\begin{document}", 1)[1].split("\\end{document}", 1)[0]
        elif "\\documentclass" in text:
            continue
        parts.append(text)
    return "\n\n".join(parts)


def _remove_environments(text: str) -> str:
    for env in DROP_ENVS:
        e = re.escape(env)
        text = re.sub(rf"\\begin\{{{e}\}}.*?\\end\{{{e}\}}", " ", text, flags=re.S)
    text = re.sub(r"\$\$.*?\$\$|\\\[.*?\\\]", " ", text, flags=re.S)
    return text


def _drop_command_with_arg(text: str, command: str) -> str:
    pattern = re.compile(rf"\\{command}\*?\s*(?:\[[^\]]*\])?\s*\{{")
    while (match := pattern.search(text)):
        _, end = balanced(text, match.end() - 1)
        text = text[:match.start()] + " " + text[end:]
    return text


def body_to_text(body: str) -> str:
    text = _remove_environments(body)
    text = CITE_RE.sub(lambda m: CITE_MARK.format(",".join(k.strip() for k in m.group(1).split(","))), text)
    for command in ("footnote", "label", "caption", "includegraphics", "vspace", "hspace", "url", "href",
                    "thanks", "bibliography", "bibliographystyle", "input", "include", "newcommand", "renewcommand"):
        text = _drop_command_with_arg(text, command)
    text = re.sub(r"\\(?:eq|auto|c|C)?ref\s*\{[^}]*\}", "[ref]", text)
    text = MATH_RE.sub(lambda m: MATH_SYMBOLS[m.group(1)], text)
    text = re.sub(r"\\(?:sub)*section\*?\s*\{([^}]*)\}", r"\n\n\1.\n\n", text)
    text = re.sub(r"\\paragraph\*?\s*\{([^}]*)\}", r"\n\n\1. ", text)
    text = re.sub(r"\\(?:item)\b", "\n\n", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^}]*\}", "\n\n", text)
    for _ in range(3):  # unwrap formatting commands, innermost first
        text = re.sub(r"\\[a-zA-Z]+\*?\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = text.replace("~", " ").replace("``", '"').replace("''", '"').replace("\\%", "%")
    text = text.replace("{", "").replace("}", "")
    return text


def sentences(text: str) -> list[str]:
    out = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        protected = paragraph
        for i, abbr in enumerate(ABBREVIATIONS):
            protected = protected.replace(abbr, f"\u0000{i}\u0000")
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z\u27e6\[(\"])", protected):
            for i, abbr in enumerate(ABBREVIATIONS):
                sentence = sentence.replace(f"\u0000{i}\u0000", abbr)
            out.append(sentence.strip())
    return out


# ---------------------------------------------------------------- pairs

def citation_pairs(files: dict[str, str]) -> tuple[list[dict], dict[str, dict]]:
    """Sentences citing exactly one reference that exists in the bibliography."""
    refs = bibliography(files)
    pairs = []
    for sentence in sentences(body_to_text(document_body(files))):
        marks = CITE_MARK_RE.findall(sentence)
        keys = [k for mark in marks for k in mark.split(",") if k]
        if len(marks) != 1 or len(keys) != 1 or keys[0] not in refs:
            continue
        claim = CITE_MARK_RE.sub("[CITATION]", sentence)
        words = len(claim.split())
        if not 8 <= words <= 80 or claim.count("[CITATION]") != 1:
            continue
        pairs.append({"claim": claim, "key": keys[0]})
    return pairs, refs
