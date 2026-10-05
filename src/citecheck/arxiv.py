"""Fetch recent arXiv papers and their LaTeX sources, politely and with caching.

arXiv asks automated clients to make at most one request every 3 seconds
(https://info.arxiv.org/help/api/tou.html). Every response is cached on disk,
so each listing page, abstract, and source archive is fetched at most once.
"""

import hashlib
import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "arxiv"
API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
USER_AGENT = "citecheck-research/0.1 (citation support evaluation)"
DELAY_S = 3.1

_last_request = 0.0


def _get(url: str, params: dict | None = None) -> httpx.Response:
    global _last_request
    wait = DELAY_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(5):
        _last_request = time.monotonic()
        response = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT},
                             timeout=120, follow_redirects=True)
        if response.status_code not in (429, 500, 502, 503):
            return response
        if attempt == 4:
            break
        retry_after = response.headers.get("Retry-After", "")
        time.sleep(float(retry_after) if retry_after.isdigit() else 60 * 2 ** attempt)
    return response


def _parse_entries(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.findall("a:entry", ATOM):
        arxiv_id = entry.find("a:id", ATOM).text.rsplit("/abs/", 1)[-1]
        entries.append({
            "arxiv_id": re.sub(r"v\d+$", "", arxiv_id),
            "title": " ".join(entry.find("a:title", ATOM).text.split()),
            "abstract": " ".join(entry.find("a:summary", ATOM).text.split()),
            "authors": [a.find("a:name", ATOM).text for a in entry.findall("a:author", ATOM)],
            "published": entry.find("a:published", ATOM).text,
            "primary_category": entry.find("arxiv:primary_category", ATOM).get("term"),
        })
    return entries


def list_recent(category: str, n: int, start_date: str, end_date: str) -> list[dict]:
    """Papers submitted in [start_date, end_date] (YYYYMMDD), newest first."""
    path = CACHE / "listings" / f"{category}_{start_date}_{end_date}_{n}.json"
    if path.exists():
        return json.loads(path.read_text())
    params = {"search_query": f"cat:{category} AND submittedDate:[{start_date}0000 TO {end_date}2359]",
              "sortBy": "submittedDate", "sortOrder": "descending", "start": 0, "max_results": n}
    response = _get(API, params)
    response.raise_for_status()
    entries = _parse_entries(response.text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=1))
    return entries


def metadata(arxiv_ids: list[str]) -> dict[str, dict]:
    """Title/abstract/authors for arXiv ids (cached per id, fetched in batches of 50)."""
    out, missing = {}, []
    for arxiv_id in arxiv_ids:
        path = CACHE / "meta" / f"{arxiv_id.replace('/', '_')}.json"
        if path.exists():
            out[arxiv_id] = json.loads(path.read_text())
        else:
            missing.append(arxiv_id)
    for i in range(0, len(missing), 50):
        batch = missing[i:i + 50]
        response = _get(API, {"id_list": ",".join(batch), "max_results": len(batch)})
        response.raise_for_status()
        for entry in _parse_entries(response.text):
            path = CACHE / "meta" / f"{entry['arxiv_id'].replace('/', '_')}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry))
            out[entry["arxiv_id"]] = entry
    return out


def title_query(title: str) -> str:
    """arXiv exact-phrase title query; punctuation breaks the API's query parser."""
    title = re.sub(r"\\['\"`^~=.]", "", title)  # LaTeX accents: Na\"ive -> Naive
    title = re.sub(r"\\[a-zA-Z]+\s*", " ", title)
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    title = " ".join(re.sub(r"[^A-Za-z0-9]+", " ", title).split())
    return f'ti:"{title}"'


def search_title(title: str, max_results: int = 5) -> list[dict]:
    query = title_query(title)
    key = hashlib.sha256(query.encode()).hexdigest()[:24]
    path = CACHE / "title_search" / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())["entries"]
    response = _get(API, {"search_query": query, "max_results": max_results})
    response.raise_for_status()
    entries = _parse_entries(response.text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"query": query, "entries": entries}))
    return entries


def download_pdf(arxiv_id: str) -> bytes | None:
    path = CACHE / "pdf" / f"{arxiv_id.replace('/', '_')}.pdf"
    if not path.exists():
        response = _get(f"https://arxiv.org/pdf/{arxiv_id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        ok = response.status_code == 200 and response.content.startswith(b"%PDF")
        path.write_bytes(response.content if ok else b"")
    data = path.read_bytes()
    return data or None


def download_source(arxiv_id: str) -> Path | None:
    """The e-print archive as served by arXiv (tar.gz, gzip'd .tex, or PDF-only)."""
    path = CACHE / "src" / f"{arxiv_id.replace('/', '_')}"
    if path.exists():
        return path if path.stat().st_size else None
    response = _get(f"https://arxiv.org/e-print/{arxiv_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if response.status_code != 200:
        path.write_bytes(b"")  # remember the failure; don't re-request
        return None
    path.write_bytes(response.content)
    return path
