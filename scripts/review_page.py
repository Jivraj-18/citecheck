"""Step 9 check: a model from a different family than the page's author reviews the
rendered page text against the data and the list of claims the page must not make.

Writes results/page_review.json.
"""

import asyncio
import functools
import http.server
import json
import threading
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from citecheck import config, llm

load_dotenv(".env")
REVIEWER = "google/gemini-3.1-pro-preview"

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory="docs")
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
    page.wait_for_function("window.__storyReady === true")
    text = page.inner_text("main")
    browser.close()
server.shutdown()

readme = Path("README.md").read_text()
limits = readme[readme.index("## Limits"):readme.index("## Results")]  # the claims the page may not make
data = {name: json.loads(Path(f"docs/data/{name}.json").read_text()) for name in ("results", "examples")}

SYSTEM = """You review a data story before it is published. Check the page text against the data files and the rules.
Report every problem: a number on the page that does not match the data; a claim the data does not support or that
overstates it (e.g. presents differences within overlapping confidence intervals as definite); anything the rules say
the page may not claim; wording about named papers that is accusatory rather than neutral; and unclear or misleading
phrasing. Be specific and quote the page text. If there are no problems, return an empty list."""
SCHEMA = {
    "type": "object",
    "properties": {"problems": {"type": "array", "items": {
        "type": "object",
        "properties": {"quote": {"type": "string"}, "problem": {"type": "string"},
                       "severity": {"type": "string", "enum": ["must_fix", "should_fix", "minor"]}},
        "required": ["quote", "problem", "severity"], "additionalProperties": False}}},
    "required": ["problems"], "additionalProperties": False,
}
user = (f"RULES:\n{limits}\n\nDATA (results.json and examples.json):\n{json.dumps(data)[:60000]}\n\n"
        f"PAGE TEXT:\n{text}")


async def main():
    models_json = json.loads(Path("docs/data/models.json").read_text())
    client = llm.LLM(budget_usd=config.BUDGET_USD, prices=config.prices_by_api_id(models_json))
    route, api_id = config.MODELS[REVIEWER]
    record = await client.call(api_id, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                               route=route, schema=SCHEMA, max_tokens=16000)
    return llm.parsed(record)


review = asyncio.run(main())
Path("results/page_review.json").write_text(json.dumps(review, indent=1))
for p in review["problems"]:
    print(f"[{p['severity']}] {p['quote'][:120]!r}\n    {p['problem']}")
print(f"{len(review['problems'])} problems; spent ${llm.spent_usd():.3f}")
