from lemonclaw.providers.catalog import (
    MODEL_CATALOG,
    apply_runtime_model_policy,
    get_fallback_chain,
    get_model_runtime_meta,
    get_runtime_default_model,
)


def teardown_function():
    apply_runtime_model_policy(None)


def test_apply_runtime_policy_updates_defaults_and_chain():
    policy = {
        'defaults': {'chat': 'gpt-5.2', 'vision': 'gemini-3.1-pro-preview'},
        'catalog': [
            {'id': 'gpt-5.2', 'label': 'GPT-5.2', 'tier': 'flagship', 'enabled': True, 'visible': True, 'description': 'x', 'capabilities': ['chat']},
            {'id': 'gpt-4.1-mini', 'label': 'GPT-4.1 Mini', 'tier': 'economy', 'enabled': True, 'visible': True, 'description': 'y', 'capabilities': ['chat', 'vision']},
            {'id': 'claude-haiku-4-5', 'label': 'Claude Haiku 4.5', 'tier': 'economy', 'enabled': True, 'visible': True, 'description': 'z', 'capabilities': ['chat']},
        ],
        'profiles': {'standard_chat': ['gpt-5.2', 'gpt-4.1-mini', 'claude-haiku-4-5']},
        'sceneProfiles': {'chat': 'standard_chat'},
        'modelProfileOverrides': {},
    }

    apply_runtime_model_policy(policy)

    assert get_runtime_default_model('chat') == 'gpt-5.2'
    assert get_runtime_default_model('vision') == 'gemini-3.1-pro-preview'
    assert get_fallback_chain('gpt-5.2', scene='chat') == ['gpt-5.2', 'gpt-4.1-mini', 'claude-haiku-4-5']


def test_apply_runtime_policy_resets_to_builtin_when_none():
    apply_runtime_model_policy({
        'defaults': {'chat': 'gpt-5.2'},
        'catalog': [],
        'profiles': {},
        'sceneProfiles': {},
        'modelProfileOverrides': {},
    })
    apply_runtime_model_policy(None)
    assert get_runtime_default_model('chat') == 'claude-sonnet-4-6'

def test_disabled_runtime_models_are_filtered_and_tagged_with_runtime_metadata():
    policy = {
        'defaults': {'chat': 'gpt-4.1-mini'},
        'catalog': [
            {'id': 'gpt-5.2', 'label': 'GPT-5.2', 'tier': 'flagship', 'enabled': False, 'visible': True, 'description': 'disabled'},
            {'id': 'gpt-4.1-mini', 'label': 'GPT-4.1 Mini', 'tier': 'economy', 'enabled': True, 'visible': True, 'description': 'enabled'},
        ],
        'profiles': {'standard_chat': ['gpt-5.2', 'gpt-4.1-mini']},
        'sceneProfiles': {'chat': 'standard_chat'},
        'modelProfileOverrides': {},
    }

    apply_runtime_model_policy(policy)

    assert [entry.id for entry in MODEL_CATALOG] == ['gpt-4.1-mini']
    assert get_fallback_chain('gpt-4.1-mini', scene='chat') == ['gpt-4.1-mini']
    assert get_runtime_default_model('chat') == 'gpt-4.1-mini'

    meta = get_model_runtime_meta('gpt-4.1-mini', scene='chat')
    assert meta['source'] == 'runtime-policy'
    assert meta['profile'] == 'standard_chat'
    assert meta['runtimePolicyActive'] is True

