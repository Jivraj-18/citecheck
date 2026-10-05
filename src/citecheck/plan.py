"""Which calls to make, in what order, and what the full run will cost."""


def pilot(items: list[dict], n_per_dataset: int) -> list[dict]:
    out, seen = [], {}
    for item in items:
        dataset = item["id"].split("/")[0]
        if seen.get(dataset, 0) < n_per_dataset:
            out.append(item)
            seen[dataset] = seen.get(dataset, 0) + 1
    return out


def cheapest_first(models: list[str], prices: dict[str, dict]) -> list[str]:
    return sorted(models, key=lambda m: prices[m]["input"] + prices[m]["output"])


def jobs(items: list[dict], models: list[str], prices: dict[str, dict]) -> list[tuple[str, dict]]:
    """Every (model, item) pair, cheapest model first, so a budget stop cuts the priciest models."""
    return [(model, item) for model in cheapest_first(models, prices) for item in items]


def projected_cost(pilot_spend: float, pilot_items: int, full_items: int) -> float:
    return pilot_spend * full_items / pilot_items
