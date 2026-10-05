"""Which models play which role, and how each is reached.

Models are named by their OpenRouter-style id (used in results and prices,
which come from docs/data/models.json) and called through the API gateway's
direct provider routes.

Not run, by the human's decision:
- All OpenAI models, for now: GPT-6 is only reachable through the gateway's
  OpenRouter route, whose key has hit its spending limit. Add them back here
  (route "openrouter") once that limit is raised.
- openai/gpt-6-astra and anthropic/claude-fable-5.1: $10/$50 per 1M tokens (cost).
- anthropic/claude-opus-5.5: deferred.
- google/gemini-3.5-flash-lite: removed.
"""

MODELS = {  # id -> (route, model id on that route)
    "anthropic/claude-sonnet-5.5": ("anthropic", "claude-sonnet-5-5"),
    "anthropic/claude-haiku-4.5": ("anthropic", "claude-haiku-4-5"),
    "google/gemini-3.1-pro-preview": ("gemini", "gemini-3.1-pro-preview"),
    "google/gemini-3.8-flash": ("gemini", "gemini-3.8-flash"),
}
# Two families only, so the panel is all four models; a real citation is flagged
# when at least 3 of 4 say it is not supported by the abstract.
PANEL = list(MODELS)
PANEL_MIN_VOTES = 3
PDF_READERS = ["anthropic/claude-sonnet-5.5", "google/gemini-3.1-pro-preview"]  # 2nd confirms published examples
CHECKER = ("gemini-3.8-flash", "gemini")  # data-prep checks: (model, route)
BUDGET_USD = 30.0


def prices_by_api_id(models_json: dict) -> dict[str, dict]:
    """models.json prices (keyed by id) re-keyed by the model id each route expects."""
    return {MODELS[m][1]: v["price_per_million"] for m, v in models_json["models"].items() if m in MODELS}
