"""Steps 3b–5: extract citation pairs from each downloaded paper, resolve
references, and keep one original + one swapped item per paper (150 papers).

Writes data/eval/arxiv.jsonl and data/eval/arxiv_dropouts.json.
"""

import json
from collections import Counter
from pathlib import Path

from citecheck import arxiv, latex, resolve
from citecheck.build import interleave, select_pair

TARGET_PAPERS = 150
papers = interleave(json.loads(Path("data/papers.json").read_text()), key="listing")  # balance cs.LG / cs.CL
items, drops = [], Counter()

for paper in papers:
    if len(items) // 2 >= TARGET_PAPERS:
        break
    source = arxiv.download_source(paper["arxiv_id"])
    if source is None:
        drops["no_source"] += 1
        continue
    files = latex.read_archive(source)
    if not any(name.endswith(".tex") for name in files):
        drops["no_tex"] += 1
        continue
    pairs, refs = latex.citation_pairs(files)
    result = select_pair(paper["arxiv_id"], pairs, refs, resolve.resolve, seed=0)
    if result["drop_reason"]:
        drops[result["drop_reason"]] += 1
    else:
        items += [{**item, "listing": paper["listing"]} for item in result["items"]]
    done = len(items) // 2
    print(f"{paper['arxiv_id']}: {result['drop_reason'] or 'kept'}  ({done} kept, drops {dict(drops)})", flush=True)

Path("data/eval/arxiv.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
Path("data/eval/arxiv_dropouts.json").write_text(json.dumps(
    {"papers_considered": sum(drops.values()) + len(items) // 2, "kept": len(items) // 2,
     "dropped": dict(drops),
     "kept_by_listing": dict(Counter(i["listing"] for i in items if i["id"].endswith("/original")))}, indent=1))
print("kept", len(items) // 2, "papers; drops", dict(drops))
