"""Tests for model semantic aliases + budget-aware routing — P3-E."""


def test_resolve_alias_known():
    from lemonclaw.providers.aliases import resolve_alias

    entry = resolve_alias("best-for-code")
    assert entry is not None
    assert entry.id == "claude-opus-4-6"


def test_resolve_alias_unknown():
    from lemonclaw.providers.aliases import resolve_alias

    assert resolve_alias("nonexistent-alias") is None


def test_resolve_alias_case_insensitive():
    from lemonclaw.providers.aliases import resolve_alias

    entry = resolve_alias("FAST-AND-CHEAP")
    assert entry is not None
    assert entry.tier == "economy"


def test_list_aliases():
    from lemonclaw.providers.aliases import list_aliases

    aliases = list_aliases()
    assert "fast-and-cheap" in aliases
    assert "best-for-code" in aliases
    assert len(aliases) == 5


def test_downgrade_tier_flagship_to_standard():
    from lemonclaw.providers.aliases import downgrade_tier

    entry = downgrade_tier("claude-opus-4-6")
    assert entry is not None
    assert entry.tier == "standard"


def test_downgrade_tier_standard_to_economy():
    from lemonclaw.providers.aliases import downgrade_tier

    entry = downgrade_tier("claude-sonnet-4-6")
    assert entry is not None
    assert entry.tier == "economy"


def test_downgrade_tier_economy_no_further():
    from lemonclaw.providers.aliases import downgrade_tier

    assert downgrade_tier("claude-haiku-4-5") is None


def test_downgrade_tier_unknown_model():
    from lemonclaw.providers.aliases import downgrade_tier

    assert downgrade_tier("nonexistent-model") is None


def test_budget_aware_select_sufficient():
    from lemonclaw.providers.aliases import budget_aware_select

    result = budget_aware_select("claude-opus-4-6", balance_usd=10.0)
    assert result == "claude-opus-4-6"  # No downgrade


def test_budget_aware_select_low_balance():
    from lemonclaw.providers.aliases import budget_aware_select

    result = budget_aware_select("claude-opus-4-6", balance_usd=0.5)
    assert result != "claude-opus-4-6"  # Downgraded


def test_budget_aware_select_economy_stays():
    from lemonclaw.providers.aliases import budget_aware_select

    result = budget_aware_select("claude-haiku-4-5", balance_usd=0.1)
    assert result == "claude-haiku-4-5"  # Can't downgrade further
