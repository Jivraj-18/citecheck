"""Step 9 check: render the data story in headless Chromium and verify it.

  uv run python scripts/check_page.py            # checks docs/ with docs/data
  uv run python scripts/check_page.py DIR OUT    # any folder (e.g. a fixture preview), screenshots to OUT

Fails (exit 1) on: console errors, page errors, a bound value that is missing,
text containing NaN / undefined / n/a / Infinity, a table row count that does
not match the data, or a broken link (http status >= 400). Screenshots: desktop
and phone widths, light and dark.
"""

import functools
import http.server
import json
import sys
import threading
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

site = Path(sys.argv[1] if len(sys.argv) > 1 else "docs").resolve()
out = Path(sys.argv[2] if len(sys.argv) > 2 else "results/screenshots")
out.mkdir(parents=True, exist_ok=True)
results = json.loads((site / "data" / "results.json").read_text())

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}/index.html"

problems = []
links = set()
with sync_playwright() as p:
    browser = p.chromium.launch()
    for scheme in ("light", "dark"):
        for name, width in (("desktop", 1280), ("phone", 390)):
            page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__storyReady === true", timeout=20000)
            problems += [f"{scheme}/{name}: console: {e}" for e in errors]
            text = page.inner_text("body")
            for bad in ("NaN", "undefined", "n/a", "Infinity"):
                if bad in text:
                    problems.append(f"{scheme}/{name}: page text contains {bad!r}")
            for b in page.evaluate("window.__bindings"):
                if b["value"] is None or not b["text"].strip():
                    problems.append(f"binding {b['path']} is empty")
            rows = page.locator("#model-table tbody tr").count()
            if rows != len(results["models"]):
                problems.append(f"table has {rows} rows, data has {len(results['models'])} models")
            overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            if overflow:
                problems.append(f"{scheme}/{name}: horizontal page scroll")
            links |= set(page.eval_on_selector_all("a[href^='http']", "els => els.map(e => e.href)"))
            page.screenshot(path=str(out / f"{scheme}-{name}.png"), full_page=True)
            page.close()
    browser.close()
server.shutdown()

for link in sorted(links):
    try:
        status = httpx.get(link, follow_redirects=True, timeout=30,
                           headers={"User-Agent": "citecheck-link-check/0.1"}).status_code
    except httpx.HTTPError as exc:
        status = str(exc)
    if not isinstance(status, int) or status >= 400:
        problems.append(f"link {link}: {status}")

print(f"checked {url} ({len(links)} external links); screenshots in {out}")
if problems:
    print("PROBLEMS:\n  " + "\n  ".join(dict.fromkeys(problems)))
    sys.exit(1)
print("all checks passed")
