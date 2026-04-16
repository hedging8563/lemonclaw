from lemonclaw.providers.catalog import (
    MODEL_CATALOG,
    apply_runtime_model_policy,
    get_fallback_chain,
    get_model_runtime_meta,
    get_runtime_default_model,
    get_runtime_memory_policy,
    resolve_model_id,
)


def teardown_function():
    apply_runtime_model_policy(None)


def test_apply_direct_runtime_config_updates_chat_vision_and_memory():
    config = {
        "chat": {
            "defaultModel": "gpt-5.2",
            "visibleModels": ["gpt-5.2", "gpt-5.4", "claude-sonnet-4-6"],
        },
        "vision": {
            "primaryModel": "gemini-3.1-pro-preview",
            "fallbackModels": ["gpt-4.1-mini"],
        },
        "memory": {
            "indexMode": "hybrid",
            "embeddingOrder": ["text-embedding-005", "gemini-embedding-001"],
        },
    }

    apply_runtime_model_policy(config)

    assert get_runtime_default_model("chat") == "gpt-5.2"
    assert get_runtime_default_model("vision") == "gemini-3.1-pro-preview"
    assert get_fallback_chain("gpt-5.2", scene="chat") == ["gpt-5.2"]
    assert get_fallback_chain("gemini-3.1-pro-preview", scene="vision") == ["gemini-3.1-pro-preview", "gpt-4.1-mini"]
    assert get_runtime_memory_policy()["embeddingOrder"] == ["text-embedding-005", "gemini-embedding-001"]


def test_apply_legacy_direct_runtime_config_shape_remains_supported():
    config = {
        "chat": {
            "defaultModel": "gpt-5.2",
            "availableModels": ["gpt-5.2", "gpt-5.4", "claude-sonnet-4-6"],
        },
        "vision": {
            "chain": ["gemini-3.1-pro-preview", "gpt-4.1-mini"],
        },
        "memory": {
            "indexMode": "hybrid",
            "embeddingOrder": ["text-embedding-005", "gemini-embedding-001"],
        },
    }

    apply_runtime_model_policy(config)

    assert [entry.id for entry in MODEL_CATALOG if not entry.hidden] == [
        "gpt-5.2",
        "gpt-5.4",
        "claude-sonnet-4-6",
    ]
    assert get_runtime_default_model("vision") == "gemini-3.1-pro-preview"


def test_apply_runtime_policy_resets_to_builtin_when_none():
    apply_runtime_model_policy({
        "chat": {"defaultModel": "gpt-5.2", "availableModels": ["gpt-5.2"]},
        "vision": {"chain": ["gpt-4.1-mini"]},
        "memory": {"indexMode": "disabled", "embeddingOrder": ["text-embedding-005"]},
    })
    apply_runtime_model_policy(None)
    assert get_runtime_default_model("chat") == "gpt-5.4"
    assert get_runtime_default_model("vision") == "gpt-4.1-mini"


def test_legacy_policy_shape_is_still_migrated_for_runtime_compatibility():
    policy = {
        "defaults": {"chat": "gpt-5.2", "vision": "gemini-3.1-pro-preview"},
        "catalog": [
            {"id": "gpt-5.2", "label": "GPT-5.2", "tier": "flagship", "enabled": True, "visible": True, "description": "x", "capabilities": ["chat"]},
            {"id": "gpt-4.1-mini", "label": "GPT-4.1 Mini", "tier": "economy", "enabled": True, "visible": True, "description": "y", "capabilities": ["chat", "vision"]},
            {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro", "tier": "flagship", "enabled": True, "visible": False, "description": "vision", "capabilities": ["chat", "vision"]},
        ],
        "profiles": {"standard_chat": ["gpt-5.2", "gpt-4.1-mini"], "vision_chat": ["gemini-3.1-pro-preview", "gpt-4.1-mini"]},
        "sceneProfiles": {"chat": "standard_chat", "vision": "vision_chat"},
        "modelProfileOverrides": {},
        "internal": {
            "memory": {
                "indexMode": "fts_only",
                "preferredEmbeddingModel": "text-embedding-005",
                "fallbackEmbeddingModels": ["gemini-embedding-001"],
            },
        },
    }

    apply_runtime_model_policy(policy)

    assert get_runtime_default_model("chat") == "gpt-5.2"
    assert get_fallback_chain("gpt-5.2", scene="chat") == ["gpt-5.2"]
    assert get_fallback_chain("gemini-3.1-pro-preview", scene="vision") == ["gemini-3.1-pro-preview", "gpt-4.1-mini"]
    assert get_runtime_memory_policy()["indexMode"] == "fts_only"


def test_visible_model_list_follows_chat_available_models_order():
    apply_runtime_model_policy({
        "chat": {
            "defaultModel": "claude-sonnet-4-6",
            "availableModels": ["claude-sonnet-4-6", "gpt-5.4", "deepseek-v3-2"],
        },
        "vision": {"chain": ["gpt-4.1-mini"]},
        "memory": {"indexMode": "auto", "embeddingOrder": ["text-embedding-005"]},
    })

    assert [entry.id for entry in MODEL_CATALOG if not entry.hidden] == [
        "claude-sonnet-4-6",
        "gpt-5.4",
        "deepseek-v3-2",
    ]
    meta = get_model_runtime_meta("claude-sonnet-4-6", scene="chat")
    assert meta["source"] == "runtime-policy"
    assert meta["profile"] == "chat"


def test_resolve_model_id_remains_exact_without_alias_rewrites():
    apply_runtime_model_policy({
        "chat": {"defaultModel": "gpt-5.4", "availableModels": ["gpt-5.4"]},
        "vision": {"chain": ["gpt-4.1-mini"]},
        "memory": {"indexMode": "auto", "embeddingOrder": ["text-embedding-005"]},
    })

    assert resolve_model_id("gpt-5.4") == "gpt-5.4"
    assert resolve_model_id("minimax-m2.5") == "minimax-m2.5"
