# Can an AI model tell whether a citation supports its claim?

A small, reproducible experiment: which LLM can check whether a citation
supports the sentence it is attached to, how reliably, and at what cost per
manuscript. The result is a data story published with GitHub Pages from
[`docs/`](docs/).

Fake references are already counted at scale. Whether a *real* reference
supports its claim is not. That needs a reader, and this experiment measures
how well models do that job.

## What it does

1. **SciFact** (Allen AI): 300 expert-labelled claim/abstract pairs
   (supports / contradicts / not enough info), 100 of each.
2. **arXiv**: recent cs.LG and cs.CL papers. A LaTeX parser extracts
   sentences that cite exactly one reference; references are matched to arXiv
   records. Per paper, one real pair and the same sentence with a different
   reference from that paper swapped in.
3. **Four models** (Claude Sonnet 5.5, Claude Haiku 4.5, Gemini 3.1 Pro,
   Gemini 3.8 Flash) judge every item with the same prompt and structured
   output. OpenAI models were not tested in this run (no API access at the
   time); the $10/$50 flagships were excluded for cost.
4. **Verification by models**: when at least 3 of 4 models say a real
   citation is not supported by the abstract, Claude Sonnet 5.5 reads the
   cited paper's full PDF; where it agrees, Gemini 3.1 Pro reads it too. Both
   then classify each confirmed case, and only cases both call a *specific
   claim the cited paper does not make* are shown as examples.
5. **Results** are scored (accuracy, macro-F1, bootstrap CIs, cost per 1,000
   checks, Pareto frontier) and written to `docs/data/`. The page reads
   every number from there.

## Setup

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repo> && cd <repo>
uv sync
uv run playwright install chromium   # only for the page check
cp .env.example .env                 # then fill in your endpoint and key
uv run pytest -q                     # offline tests, no API calls
```

`.env` needs a gateway URL and key. Models are called through these routes
under it (see `src/citecheck/config.py` and `src/citecheck/llm.py`):
`{GATEWAY_BASE_URL}/anthropic` (Anthropic Messages API, via the official SDK),
`{GATEWAY_BASE_URL}/gemini/v1beta/openai` (Gemini's OpenAI-compatible API),
and optionally `{GATEWAY_BASE_URL}/openrouter/v1`. To call providers directly,
point those routes at the providers' own endpoints.

## Run the pipeline

```bash
uv run python scripts/check_models.py      # step 1: current models, prices, one probe call each
uv run python scripts/fetch_sources.py     # step 3a: list ~300 recent papers (sources download on demand)
uv run python -c "from pathlib import Path; from citecheck import scifact; print(scifact.build(Path('data/eval/scifact.jsonl')))"
uv run python scripts/build_arxiv_set.py   # steps 3–5: parse, resolve, pick one pair per paper
uv run python scripts/check_dataprep.py    # model spot-checks of extraction and reference matching
uv run python scripts/run_models.py --pilot 10   # pilot + projected cost of the full run
uv run python scripts/run_models.py        # step 6: full run
uv run python scripts/verify_panel.py      # step 7: panel flags, agreement, full-PDF reads
uv run python scripts/classify_confirmed.py   # step 7b: what kind of problem each confirmed case is
uv run python scripts/compute_results.py   # step 8: docs/data/results.json and examples.json
uv run python scripts/check_page.py        # step 9: render + verify the page, screenshots
uv run python scripts/review_page.py       # step 9: a model from another family reviews the page text
```

Preview the page locally:

```bash
python -m http.server -d docs   # then open http://localhost:8000
```

## Costs and politeness

- Every LLM call is cached on disk (`cache/llm/`) with the **raw response**
  exactly as returned, plus the request and a timestamp. A cached call is never
  sent again, so re-runs are free and resumable.
- Spend is logged per call (`cache/llm/ledger.jsonl`) and the run stops at the
  budget in `src/citecheck/config.py`. Where a route does not report cost, it
  is estimated from list prices and the reported tokens, counting reasoning
  tokens as output. The whole experiment cost about $14.
- arXiv is queried at most once every 3 seconds, with backoff on 429/503, and
  every response is cached.

## Data and licenses

- SciFact: [allenai/scifact](https://github.com/allenai/scifact), CC BY-NC 2.0.
- arXiv metadata and sources: via the [arXiv API](https://info.arxiv.org/help/api/),
  used under its terms of use. Paper texts are not redistributed here.

## Limits

- The sample is not designed to measure how common unsupported citations are.
- arXiv examples are verified by models reading full text, not by experts.
- SciFact is biomedical; the arXiv set is machine learning. Results are reported separately.
- Swapped citations are easier to catch than real mistakes.
- Flagship models priced at $10/$50 per million tokens were not tested, for cost;
  OpenAI models were not tested in this run.
- The arXiv set leans toward citations of arXiv papers (87% of references were
  matched by arXiv id).

## Results

See the [data story](docs/index.html). In short: on SciFact, Gemini 3.8 Flash
came within 2 points of the top scorer (Gemini 3.1 Pro) for about a quarter of
the cost; on the arXiv citations, Claude Haiku 4.5 came within 2 points of the
top scorer (Claude Sonnet 5.5) at about $1.36 per 1,000 checks. Both gaps are
within the margin of error. The top scorer came from a different family on each
dataset. All numbers are in `docs/data/results.json`.
