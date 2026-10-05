from citecheck import config, plan

ITEMS = [{"id": f"scifact/{i}"} for i in range(5)] + [{"id": f"arxiv/{i}"} for i in range(5)]
PRICES = {"m_cheap": {"input": 0.1, "output": 0.5}, "m_mid": {"input": 2, "output": 10},
          "m_pricey": {"input": 4, "output": 20}}


def test_pilot_takes_first_n_of_each_dataset():
    picked = plan.pilot(ITEMS, n_per_dataset=2)
    assert [i["id"] for i in picked] == ["scifact/0", "scifact/1", "arxiv/0", "arxiv/1"]


def test_jobs_run_cheapest_model_first_over_all_items():
    jobs = plan.jobs(ITEMS[:2], ["m_pricey", "m_cheap", "m_mid"], PRICES)
    assert [m for m, _ in jobs] == ["m_cheap"] * 2 + ["m_mid"] * 2 + ["m_pricey"] * 2


def test_projected_cost_scales_pilot_spend_to_full_run():
    assert plan.projected_cost(pilot_spend=0.5, pilot_items=20, full_items=600) == 15.0


def test_config_runs_claude_and_gemini_only_via_direct_routes():
    assert set(config.MODELS) == {"anthropic/claude-sonnet-5.5", "anthropic/claude-haiku-4.5",
                                  "google/gemini-3.1-pro-preview", "google/gemini-3.8-flash"}
    assert all(route in ("anthropic", "gemini") for route, _ in config.MODELS.values())
    assert not any(m.startswith("openai/") for m in config.MODELS)  # dropped for now (OpenRouter key exhausted)
    assert set(config.PANEL) <= set(config.MODELS) and config.PANEL_MIN_VOTES == 3
    assert set(config.PDF_READERS) <= set(config.MODELS)


def test_cheapest_first_orders_models_by_price():
    assert plan.cheapest_first(["m_pricey", "m_cheap", "m_mid"], PRICES) == ["m_cheap", "m_mid", "m_pricey"]
