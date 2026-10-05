"""Step 7b: classify each confirmed-unsupported citation (both full-text readers agreed).

Both reader models classify every case; a case counts as "specific_claim_unsupported"
(and may be published as an example) only if both agree. Otherwise it is
"disagreement" or the category both chose.

Writes results/classification.json.
"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from citecheck import config, llm, verify

load_dotenv(".env")
verification = json.loads(Path("results/verification.json").read_text())
items = {i["id"]: i for i in (json.loads(line) for line in Path("data/eval/arxiv.jsonl").read_text().splitlines())}
models_json = json.loads(Path("docs/data/models.json").read_text())


async def main():
    client = llm.LLM(budget_usd=config.BUDGET_USD, prices=config.prices_by_api_id(models_json))
    out = {}

    async def one(item_id):
        votes = {}
        for model in config.PDF_READERS:
            route, api_id = config.MODELS[model]
            record = await client.call(api_id, verify.classify_messages(items[item_id], verification["pdf_reads"][item_id]),
                                       route=route, schema=verify.CLASSIFY_SCHEMA, max_tokens=8000)
            votes[model] = llm.parsed(record)
        categories = {v["category"] for v in votes.values()}
        out[item_id] = {"category": categories.pop() if len(categories) == 1 else "disagreement", "votes": votes}

    await asyncio.gather(*(one(i) for i in verification["confirmed_unsupported"]))
    return out


classification = asyncio.run(main())
Path("results/classification.json").write_text(json.dumps(classification, indent=1))
counts = {}
for c in classification.values():
    counts[c["category"]] = counts.get(c["category"], 0) + 1
print("categories:", counts, f"| spent ${llm.spent_usd():.3f}")
for item_id, c in sorted(classification.items()):
    print(f"{item_id}: {c['category']}  ({' / '.join(v['category'] for v in c['votes'].values())})")
