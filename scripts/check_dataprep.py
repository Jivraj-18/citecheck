"""Steps 3–4 checks, done by an LLM (config.CHECKER):
- 20 random original items: is the extracted sentence faithful to the LaTeX source?
- 50 random resolved references: is the matched paper the same work as the bibliography entry?

Writes results/dataprep_checks.json.
"""

import asyncio
import json
import random
from pathlib import Path

from dotenv import load_dotenv

from citecheck import arxiv, config, judge, latex, llm

load_dotenv(".env")
items = [json.loads(line) for line in Path("data/eval/arxiv.jsonl").read_text().splitlines()]
rng = random.Random(0)
originals = rng.sample([i for i in items if i["label"] == "supports"], 20)
references = rng.sample(items, 50)  # originals and swapped-in references alike
model, route = config.CHECKER


async def main():
    client = llm.LLM(budget_usd=config.BUDGET_USD)
    extraction, resolution = [], []

    async def check_extraction(item):
        files = latex.read_archive(arxiv.download_source(item["paper_id"]))
        tex = "\n".join(t for name, t in files.items() if name.endswith(".tex"))
        window = judge.source_window(tex, item["ref_key"], item["claim"])
        if window is None:
            extraction.append({"item_id": item["id"], "faithful": False, "problem": "citation key not found in source"})
            return
        record = await client.call(model, judge.extraction_messages(window, item["ref_key"], item["claim"]),
                                   route=route, schema=judge.EXTRACTION_SCHEMA)
        extraction.append({"item_id": item["id"], **llm.parsed(record)})

    async def check_resolution(item):
        record = await client.call(model, judge.resolution_messages(item["ref_raw"], item["cited_title"],
                                                                    item["cited_authors"]),
                                   route=route, schema=judge.RESOLUTION_SCHEMA)
        resolution.append({"item_id": item["id"], "method": item["resolve_method"], **llm.parsed(record)})

    await asyncio.gather(*(check_extraction(i) for i in originals), *(check_resolution(i) for i in references))
    return extraction, resolution


extraction, resolution = asyncio.run(main())
summary = {
    "checker": f"{model} ({route} route)",
    "extraction": {"checked": len(extraction),
                   "faithful": sum(e["faithful"] for e in extraction),
                   "citation_position_correct": sum(e.get("citation_position_correct", False) for e in extraction),
                   "details": extraction},
    "resolution": {"checked": len(resolution), "same_work": sum(r["same_work"] for r in resolution),
                   "details": resolution},
}
Path("results").mkdir(exist_ok=True)
Path("results/dataprep_checks.json").write_text(json.dumps(summary, indent=1))
print(f"extraction faithful {summary['extraction']['faithful']}/{len(extraction)}, "
      f"citation position correct {summary['extraction']['citation_position_correct']}/{len(extraction)}; "
      f"resolution same work {summary['resolution']['same_work']}/{len(resolution)}")
for e in extraction:
    if not (e["faithful"] and e.get("citation_position_correct")):
        print("EXTRACTION PROBLEM", e)
for r in resolution:
    if not r["same_work"]:
        print("RESOLUTION PROBLEM", r)
