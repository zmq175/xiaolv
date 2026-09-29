from decimal import Decimal

import pytest

from xiaolv.domain.model_budget import BudgetPolicy


@pytest.mark.parametrize(
    "changes",
    [
        {"monthly_limit": 1.0},
        {"monthly_limit": Decimal(-1)},
        {"monthly_limit": Decimal("NaN")},
        {"input_per_million": Decimal("Infinity")},
        {"output_per_million": Decimal("-0.1")},
        {"cached_input_per_million": Decimal(2)},
        {"price_version": " "},
        {"model": ""},
        {"pool_id": 1},
        {"monthly_limit": Decimal("0.0000001")},
        {"monthly_limit": Decimal(100000000000000)},
    ],
)
def test_budget_policy_rejects_ambiguous_or_unrepresentable_prices(changes):
    values = {
        "pool_id": "external",
        "provider_id": "synthetic",
        "model": "synthetic",
        "price_version": "test-v1",
        "monthly_limit": Decimal(1),
        "input_per_million": Decimal(1),
        "output_per_million": Decimal(2),
    }
    values.update(changes)
    with pytest.raises(ValueError, match="budget policy"):
        BudgetPolicy(**values)
