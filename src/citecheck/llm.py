"""Cached, throttled, budget-capped LLM calls through the API gateway.

Every successful call is written to disk as the *raw* JSON body the API
returned (reasoning fields, usage, cost, provider, everything), together with
the exact request and a timestamp. A request whose cache file exists is never
sent again. Parsed values are always derived from the raw dump.

Routes:
- "anthropic":  {GATEWAY_BASE_URL}/anthropic via the Anthropic SDK, model ids like "claude-sonnet-5-5"
- "gemini":     {GATEWAY_BASE_URL}/gemini/v1beta/openai (OpenAI-compatible), ids like "gemini-3.8-flash"
- "openrouter": {GATEWAY_BASE_URL}/openrouter/v1 (OpenAI-compatible), ids like "openai/gpt-6.1-sol"

OpenRouter reports each call's cost; for the direct routes the cost is
estimated from list prices × tokens, counting reasoning tokens as output.
"""

import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import openai

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "cache" / "llm"
LEDGER = CACHE_DIR / "ledger.jsonl"  # one line per paid (non-cached) call
ERRORS = CACHE_DIR / "errors.jsonl"
ROUTES = {"openrouter": "openrouter/v1", "gemini": "gemini/v1beta/openai"}


class BudgetExceeded(RuntimeError):
    pass


class OutOfCredit(RuntimeError):
    """HTTP 402 from OpenRouter: the key's credit limit is reached. Never retried."""


class Refused(RuntimeError):
    """The model declined to answer (a refusal stop reason)."""


def estimate_cost(route: str, raw: dict, price: dict | None) -> float | None:
    usage = raw.get("usage") or {}
    if usage.get("cost") is not None:
        return usage["cost"]
    if price is None:
        return None
    if route == "anthropic":  # output_tokens already includes thinking tokens
        tokens_in = (usage.get("input_tokens", 0) + (usage.get("cache_creation_input_tokens") or 0)
                     + (usage.get("cache_read_input_tokens") or 0))
        tokens_out = usage.get("output_tokens", 0)
    else:  # OpenAI-compatible: hidden reasoning shows up only in total_tokens
        tokens_in = usage.get("prompt_tokens", 0)
        total = usage.get("total_tokens")
        tokens_out = total - tokens_in if total else usage.get("completion_tokens", 0)
    return (tokens_in * price["input"] + tokens_out * price["output"]) / 1e6


def request_key(route: str, request: dict) -> str:
    return hashlib.sha256(json.dumps({"route": route, **request}, sort_keys=True).encode()).hexdigest()


def cache_path(key: str) -> Path:
    return CACHE_DIR / key[:2] / f"{key}.json"


def spent_usd() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line).get("cost_usd") or 0.0 for line in LEDGER.read_text().splitlines() if line)


class RateLimiter:
    """Spaces request starts at least 60/rpm seconds apart."""

    def __init__(self, rpm: float):
        self.interval = 60.0 / rpm
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        if start > now:
            await asyncio.sleep(start - now)


class LLM:
    def __init__(self, budget_usd: float = 30.0, concurrency: int = 4, rpm: float = 60,
                 prices: dict[str, dict] | None = None):
        base = os.environ["GATEWAY_BASE_URL"].rstrip("/")
        key = os.environ["GATEWAY_API_KEY"]
        self.clients = {
            name: openai.AsyncOpenAI(base_url=f"{base}/{path}", api_key=key, max_retries=0, timeout=600)
            for name, path in ROUTES.items()
        }
        self.clients["anthropic"] = anthropic.AsyncAnthropic(base_url=f"{base}/anthropic", auth_token=key,
                                                             max_retries=0, timeout=600)
        self.prices = prices or {}  # api model id -> {"input": $/M, "output": $/M}
        self.budget_usd = budget_usd
        self.semaphore = asyncio.Semaphore(concurrency)
        self.limiter = RateLimiter(rpm)
        self.file_lock = asyncio.Lock()
        self.stats = {"cached": 0, "sent": 0, "errors": 0}

    async def call(self, model: str, messages: list[dict], *, route: str = "openrouter",
                   schema: dict | None = None, max_tokens: int = 4000, extra: dict | None = None) -> dict:
        """Returns the cache record: {"request", "route", "timestamp", "raw", "cost_usd"}."""
        if route == "anthropic":
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            request = {"model": model, "max_tokens": max_tokens,
                       "messages": [m for m in messages if m["role"] != "system"], **(extra or {})}
            if system:
                request["system"] = system
            if schema is not None:
                request["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        else:
            request = {"model": model, "messages": messages, "max_tokens": max_tokens, **(extra or {})}
            if schema is not None:
                request["response_format"] = {"type": "json_schema",
                                              "json_schema": {"name": "result", "schema": schema, "strict": True}}
        key = request_key(route, request)
        path = cache_path(key)
        if path.exists():
            self.stats["cached"] += 1
            return json.loads(path.read_text())

        if spent_usd() >= self.budget_usd:
            raise BudgetExceeded(f"spent ${spent_usd():.2f} of ${self.budget_usd:.2f} budget")

        for attempt in range(4):
            async with self.semaphore:
                await self.limiter.wait()
                try:
                    if route == "anthropic":
                        response = await self.clients[route].messages.with_raw_response.create(**request)
                        body = await response.text()
                    else:
                        response = await self.clients[route].chat.completions.with_raw_response.create(**request)
                        body = response.http_response.text
                    break
                except (openai.APIStatusError, anthropic.APIStatusError) as exc:
                    await self._log_error(model, route, exc.status_code, exc.response.text)
                    if exc.status_code == 402:
                        raise OutOfCredit(exc.response.text[:300]) from exc
                    if exc.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                        raise
                except (openai.APIConnectionError, anthropic.APIConnectionError) as exc:
                    await self._log_error(model, route, None, str(exc))
                    if attempt == 3:
                        raise
            await asyncio.sleep(30 * (attempt + 1))  # back off outside the semaphore

        raw = json.loads(body)
        record = {
            "request": request,
            "route": route,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw": raw,
            "cost_usd": estimate_cost(route, raw, self.prices.get(model)),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        async with self.file_lock:
            path.write_text(json.dumps(record))
            with open(LEDGER, "a") as f:
                f.write(json.dumps({"key": key, "model": model, "route": route, "timestamp": record["timestamp"],
                                    "usage": raw.get("usage"), "cost_usd": record["cost_usd"]}) + "\n")
        self.stats["sent"] += 1
        return record

    async def _log_error(self, model, route, status, body) -> None:
        self.stats["errors"] += 1
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        async with self.file_lock:
            with open(ERRORS, "a") as f:
                f.write(json.dumps({"model": model, "route": route, "status": status, "body": str(body)[:2000],
                                    "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")


def content(record: dict) -> str:
    raw = record["raw"]
    if "choices" in raw:  # OpenAI-compatible
        message = raw["choices"][0]["message"]
        if message.get("refusal"):
            raise Refused(message["refusal"])
        return message.get("content") or ""
    if raw.get("stop_reason") == "refusal":  # Anthropic
        raise Refused(json.dumps(raw.get("stop_details")))
    return next((b["text"] for b in raw.get("content", []) if b.get("type") == "text"), "")


def parsed(record: dict) -> dict:
    return json.loads(content(record))
