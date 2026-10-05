"""Step 1: save the OpenRouter /models entries for our models (prices, dates)
and probe each with one small structured call. Reports remaining credit problems.

Writes docs/data/models.json.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from citecheck import config, judge, llm

load_dotenv(".env")
base = os.environ["GATEWAY_BASE_URL"].rstrip("/")
listing = httpx.get(f"{base}/openrouter/v1/models", timeout=120,
                    headers={"Authorization": f"Bearer {os.environ['GATEWAY_API_KEY']}"}).json()["data"]
by_id = {m["id"]: m for m in listing}

wanted = sorted(config.MODELS)
models = {}
for model_id in wanted:
    entry = by_id.get(model_id)
    if entry is None:
        print(f"MISSING from /models: {model_id}")
        continue
    models[model_id] = {
        "name": entry["name"],
        "created": datetime.fromtimestamp(entry["created"], timezone.utc).date().isoformat(),
        "price_per_million": {"input": round(float(entry["pricing"]["prompt"]) * 1e6, 4),
                              "output": round(float(entry["pricing"]["completion"]) * 1e6, 4)},
    }

# newer models in the same families, so the run can be updated if the lineup moved
families = {m.split("/")[0] for m in wanted}
newest = {}
for entry in listing:
    vendor = entry["id"].split("/")[0]
    if vendor in families and ":" not in entry["id"] and not entry["id"].startswith("~"):
        newest.setdefault(vendor, []).append((entry["created"], entry["id"]))
for vendor, rows in sorted(newest.items()):
    print(vendor, "newest:", [i for _, i in sorted(rows, reverse=True)[:4]])

probe_item = {"claim": "Daily aspirin lowers heart-attack risk [CITATION].", "cited_title": "Aspirin trial",
              "cited_abstract": "In a randomized trial, daily aspirin lowered myocardial infarction incidence by 44%."}


async def probe():
    client = llm.LLM(budget_usd=config.BUDGET_USD, concurrency=1, rpm=20,
                     prices=config.prices_by_api_id({"models": models}))
    for model_id in models:
        route, api_id = config.MODELS[model_id]
        models[model_id]["route"], models[model_id]["api_id"] = route, api_id
        try:
            record = await client.call(api_id, judge.messages(probe_item), route=route, schema=judge.SCHEMA,
                                       max_tokens=8000)
            models[model_id]["probe"] = {"ok": True, "verdict": llm.parsed(record)["verdict"],
                                         "cost_usd": record["cost_usd"]}
        except llm.OutOfCredit as exc:
            models[model_id]["probe"] = {"ok": False, "error": "out_of_credit", "detail": str(exc)[:200]}
            print(f"{model_id}: OUT OF CREDIT — stopping probes")
            break
        except Exception as exc:  # report, keep going
            models[model_id]["probe"] = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:200]}
        print(model_id, models[model_id]["probe"])


asyncio.run(probe())
Path("docs/data").mkdir(parents=True, exist_ok=True)
Path("docs/data/models.json").write_text(json.dumps(
    {"fetched": datetime.now(timezone.utc).isoformat(), "source": "prices: OpenRouter /models list via the API gateway; calls: the gateway's direct provider routes",
     "models": models}, indent=1))
print(f"spent so far: ${llm.spent_usd():.4f}")
