"""Step 3a: pick ~300 recent cs.LG / cs.CL papers and download their LaTeX sources."""

import json
from pathlib import Path

from citecheck import arxiv

papers, seen = [], set()
for category in ("cs.LG", "cs.CL"):
    picked = 0
    for entry in arxiv.list_recent(category, 200, "20260901", "20260920"):
        if entry["arxiv_id"] in seen or picked == 150:
            continue
        seen.add(entry["arxiv_id"])
        papers.append({**entry, "listing": category})
        picked += 1

Path("data/papers.json").write_text(json.dumps(papers, indent=1))
ok = 0
for i, paper in enumerate(papers, 1):
    if arxiv.download_source(paper["arxiv_id"]):
        ok += 1
    if i % 25 == 0 or i == len(papers):
        print(f"{i}/{len(papers)} fetched, {ok} with source", flush=True)
