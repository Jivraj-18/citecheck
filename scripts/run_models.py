"""Step 6: every model judges every item (cached; resumable; budget-capped).

  uv run python scripts/run_models.py --pilot 10   # 10 items per dataset, then prints a cost projection
  uv run python scripts/run_models.py              # full run

Writes results/verdicts.jsonl (one row per model × item, derived from the raw cache).
"""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from citecheck import config, judge, llm, plan

parser = argparse.ArgumentParser()
parser.add_argument("--pilot", type=int, help="items per dataset for a pilot run")
parser.add_argument("--models", help="comma-separated override of config.MODELS")
args = parser.parse_args()
load_dotenv(".env")

items = [json.loads(line) for name in ("scifact", "arxiv")
         for line in Path(f"data/eval/{name}.jsonl").read_text().splitlines()]
full_items = len(items)
if args.pilot:
    items = plan.pilot(items, args.pilot)
models = args.models.split(",") if args.models else list(config.MODELS)
models_json = json.loads(Path("docs/data/models.json").read_text())
prices = {m: v["price_per_million"] for m, v in models_json["models"].items()}
spent_before = llm.spent_usd()


async def main():
    client = llm.LLM(budget_usd=config.BUDGET_USD, prices=config.prices_by_api_id(models_json))
    rows = []

    async def one(model, item):
        try:
            route, api_id = config.MODELS[model]
            record = await client.call(api_id, judge.messages(item), route=route, schema=judge.SCHEMA, max_tokens=8000)
            out = llm.parsed(record)
            rows.append({"item_id": item["id"], "model": model, "verdict": out["verdict"],
                         "confidence": out["confidence"], "rationale": out["rationale"],
                         "cost_usd": record["cost_usd"], "usage": record["raw"].get("usage")})
        except (llm.BudgetExceeded, llm.OutOfCredit):
            raise
        except llm.Refused as exc:
            rows.append({"item_id": item["id"], "model": model, "refused": str(exc)[:300]})
        except Exception as exc:
            rows.append({"item_id": item["id"], "model": model, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})

    for model in plan.cheapest_first(models, prices):  # one model at a time, cheapest first
        await asyncio.gather(*(one(model, item) for item in items))
        done = [r for r in rows if r["model"] == model]
        print(f"{model}: {sum('verdict' in r for r in done)} ok, {sum('error' in r for r in done)} errors; "
              f"spent so far ${llm.spent_usd():.3f}", flush=True)
    return rows, client.stats


rows, stats = asyncio.run(main())
Path("results").mkdir(exist_ok=True)
out = Path("results/verdicts_pilot.jsonl" if args.pilot else "results/verdicts.jsonl")
out.write_text("".join(json.dumps(r) + "\n" for r in rows))
spent = llm.spent_usd() - spent_before
print(f"calls: {stats}; spent this run: ${spent:.3f}")
if args.pilot and stats["sent"]:
    print(f"projected full run ({full_items} items): ${plan.projected_cost(spent, len(items), full_items):.2f}")
