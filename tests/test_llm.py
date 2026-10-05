import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from citecheck import llm

RAW = {"id": "gen-1", "choices": [{"message": {"content": '{"verdict": "supports"}',
                                               "reasoning": "step by step..."}, "finish_reason": "stop"}],
       "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.002}, "provider": "SomeProvider"}


class FakeCompletions:
    def __init__(self, error_status=None):
        self.calls = 0
        self.error_status = error_status

    async def create(self, **request):
        self.calls += 1
        if self.error_status:
            response = httpx.Response(self.error_status, text='{"error": "nope"}',
                                      request=httpx.Request("POST", "http://gateway"))
            raise openai.APIStatusError("error", response=response, body=None)
        return SimpleNamespace(http_response=SimpleNamespace(text=json.dumps(RAW)))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("GATEWAY_API_KEY", "k")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(llm, "ERRORS", tmp_path / "errors.jsonl")
    c = llm.LLM(budget_usd=1.0, rpm=60_000)
    return c


def install(c, completions):
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=completions)))
    c.clients = {"openrouter": fake, "gemini": fake}
    return completions


def test_raw_response_is_stored_verbatim_and_second_call_is_free(client):
    fake = install(client, FakeCompletions())
    messages = [{"role": "user", "content": "hi"}]
    first = asyncio.run(client.call("openai/gpt-6-luna", messages))
    second = asyncio.run(client.call("openai/gpt-6-luna", messages))
    assert fake.calls == 1
    assert first["raw"] == RAW == second["raw"]  # reasoning, provider, usage all kept
    assert first["request"]["max_tokens"] == 4000 and first["cost_usd"] == 0.002
    assert llm.spent_usd() == pytest.approx(0.002)
    assert llm.parsed(first) == {"verdict": "supports"}


def test_different_model_is_a_different_cache_entry(client):
    fake = install(client, FakeCompletions())
    messages = [{"role": "user", "content": "hi"}]
    asyncio.run(client.call("openai/gpt-6-luna", messages))
    asyncio.run(client.call("google/gemini-3.8-flash", messages))
    assert fake.calls == 2


def test_budget_exceeded_stops_before_sending(client):
    fake = install(client, FakeCompletions())
    llm.LEDGER.write_text(json.dumps({"cost_usd": 1.5}) + "\n")
    with pytest.raises(llm.BudgetExceeded):
        asyncio.run(client.call("openai/gpt-6-luna", [{"role": "user", "content": "hi"}]))
    assert fake.calls == 0


def test_out_of_credit_is_not_retried_and_is_logged(client):
    fake = install(client, FakeCompletions(error_status=402))
    with pytest.raises(llm.OutOfCredit):
        asyncio.run(client.call("openai/gpt-6-luna", [{"role": "user", "content": "hi"}]))
    assert fake.calls == 1
    assert json.loads(llm.ERRORS.read_text().splitlines()[0])["status"] == 402


ANTHROPIC_RAW = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                 "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                             {"type": "text", "text": '{"verdict": "contradicts"}'}],
                 "stop_reason": "end_turn", "usage": {"input_tokens": 200, "output_tokens": 300}}


class FakeAnthropicMessages:
    def __init__(self):
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)

        class Raw:
            async def text(self):
                return json.dumps(ANTHROPIC_RAW)
        return Raw()


def test_anthropic_route_moves_system_prompt_and_sets_structured_output(client):
    fake = FakeAnthropicMessages()
    client.clients["anthropic"] = SimpleNamespace(messages=SimpleNamespace(with_raw_response=fake))
    client.prices = {"claude-sonnet-5-5": {"input": 2.0, "output": 10.0}}
    schema = {"type": "object", "properties": {"verdict": {"type": "string"}}, "required": ["verdict"],
              "additionalProperties": False}
    messages = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}]
    record = asyncio.run(client.call("claude-sonnet-5-5", messages, route="anthropic", schema=schema))
    sent = fake.requests[0]
    assert sent["system"] == "SYS" and sent["messages"] == [{"role": "user", "content": "hi"}]
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert record["raw"] == ANTHROPIC_RAW
    assert llm.parsed(record) == {"verdict": "contradicts"}
    # $2/M in × 200 + $10/M out × 300 (output includes thinking tokens)
    assert record["cost_usd"] == pytest.approx(0.0004 + 0.003)
    assert llm.spent_usd() == pytest.approx(0.0034)


def test_estimate_cost_counts_hidden_reasoning_on_openai_compatible_routes():
    gemini_raw = {"usage": {"prompt_tokens": 245, "completion_tokens": 68, "total_tokens": 666}}
    # output billed = total - prompt = 421 (68 visible + 353 reasoning)
    assert llm.estimate_cost("gemini", gemini_raw, {"input": 2.0, "output": 12.0}) == \
        pytest.approx((245 * 2.0 + 421 * 12.0) / 1e6)
    assert llm.estimate_cost("openrouter", {"usage": {"cost": 0.01}}, None) == 0.01
    assert llm.estimate_cost("gemini", gemini_raw, None) is None


def test_refusal_is_reported_not_parsed():
    record = {"route": "anthropic", "raw": {**ANTHROPIC_RAW, "stop_reason": "refusal", "content": []}}
    with pytest.raises(llm.Refused):
        llm.parsed(record)
