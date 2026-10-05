"""Step 7: panel flags (reusing main-run verdicts), agreement, and full-PDF reads.

1. Flag originals where >= 2 of 3 panel models say "not supported" (no new calls).
2. Report swapped pairs all 3 panel models call "supported" (possible label noise).
3. Fleiss' kappa of the panel on all arXiv items.
4. Flagged originals: PDF_READERS[0] reads the cited paper's full PDF.
5. Where it confirms "not supported", PDF_READERS[1] reads it too; only items
   both confirm may be published as examples.

Writes results/verification.json.
"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from citecheck import arxiv, config, llm, verify

load_dotenv(".env")
verdicts = [json.loads(line) for line in Path("results/verdicts.jsonl").read_text().splitlines()]
items = {i["id"]: i for i in (json.loads(line) for line in Path("data/eval/arxiv.jsonl").read_text().splitlines())}

flagged = verify.flag_originals(verdicts, config.PANEL, min_votes=config.PANEL_MIN_VOTES)
noise = verify.possible_label_noise(verdicts, config.PANEL)
table = {}
for row in verdicts:
    if row["item_id"].startswith("arxiv/") and row["model"] in config.PANEL and "verdict" in row:
        table.setdefault(row["item_id"], {})[row["model"]] = row["verdict"]
ratings = [[votes[m] for m in config.PANEL] for votes in table.values() if len(votes) == len(config.PANEL)]
kappa = verify.fleiss_kappa(ratings)
print(f"panel: {len(flagged)} originals flagged, {len(noise)} swapped possibly noisy, kappa={kappa:.3f} "
      f"over {len(ratings)} items")


async def read(client, model, item):
    pdf = arxiv.download_pdf(item["cited_arxiv_id"])
    if pdf is None:
        return {"error": "pdf_unavailable"}
    try:
        route, api_id = config.MODELS[model]
        record = await client.call(api_id, verify.pdf_messages(item, pdf, route), route=route,
                                   schema=verify.PDF_SCHEMA, max_tokens=8000)
        return {**llm.parsed(record), "cost_usd": record["cost_usd"]}
    except (llm.BudgetExceeded, llm.OutOfCredit):
        raise
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}


async def main():
    models_json = json.loads(Path("docs/data/models.json").read_text())
    client = llm.LLM(budget_usd=config.BUDGET_USD, concurrency=2, rpm=20,
                     prices=config.prices_by_api_id(models_json))
    first, second = config.PDF_READERS
    reads = {}
    for item_id in flagged:  # sequential: PDFs are large and arXiv downloads are throttled anyway
        reads[item_id] = {first: await read(client, first, items[item_id])}
        if reads[item_id][first].get("verdict") not in (None, "supports"):
            reads[item_id][second] = await read(client, second, items[item_id])
        print(item_id, {m: r.get("verdict", r.get("error")) for m, r in reads[item_id].items()}, flush=True)
    return reads


reads = asyncio.run(main())
first, second = config.PDF_READERS
confirmed = [i for i, r in reads.items()
             if r[first].get("verdict") not in (None, "supports") and r.get(second, {}).get("verdict") not in (None, "supports")]
Path("results/verification.json").write_text(json.dumps({
    "panel": config.PANEL, "fleiss_kappa": kappa, "kappa_items": len(ratings),
    "flagged_originals": flagged, "possible_label_noise_swapped": noise,
    "pdf_reads": reads, "confirmed_unsupported": confirmed,
}, indent=1))
print(f"confirmed not supported by two full-text reads: {len(confirmed)}; spent ${llm.spent_usd():.3f}")
