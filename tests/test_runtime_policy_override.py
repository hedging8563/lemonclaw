from lemonclaw.providers.catalog import (
    MODEL_CATALOG,
    apply_runtime_model_policy,
    get_fallback_chain,
    get_model_runtime_meta,
    get_runtime_default_model,
    resolve_model_id,
)


def teardown_function():
    apply_runtime_model_policy(None)


def test_apply_runtime_policy_updates_defaults_and_chain():
    policy = {
        'defaults': {'chat': 'gpt-5.2', 'vision': 'gemini-3.1-pro-preview'},
        'catalog': [
            {'id': 'gpt-5.2', 'label': 'GPT-5.2', 'tier': 'flagship', 'enabled': True, 'visible': True, 'description': 'x', 'capabilities': ['chat']},
            {'id': 'gemini-3.1-pro-preview', 'label': 'Gemini 3.1 Pro', 'tier': 'flagship', 'enabled': True, 'visible': True, 'description': 'vision', 'capabilities': ['chat', 'vision']},
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
    assert get_runtime_default_model('chat') == 'gpt-5.4'

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

def test_runtime_policy_falls_back_to_builtin_for_inactive_non_chat_defaults():
    policy = {
        'defaults': {'chat': 'gpt-5.2', 'vision': 'gemini-3.1-pro-preview'},
        'catalog': [
            {'id': 'gpt-5.2', 'label': 'GPT-5.2', 'tier': 'flagship', 'enabled': True, 'visible': True, 'description': 'x', 'capabilities': ['chat']},
            {'id': 'gemini-3.1-pro-preview', 'label': 'Gemini 3.1 Pro', 'tier': 'flagship', 'enabled': False, 'visible': True, 'description': 'vision', 'capabilities': ['chat', 'vision']},
        ],
        'profiles': {'standard_chat': ['gpt-5.2']},
        'sceneProfiles': {'chat': 'standard_chat'},
        'modelProfileOverrides': {},
    }

    apply_runtime_model_policy(policy)

    assert get_runtime_default_model('chat') == 'gpt-5.2'
    assert get_runtime_default_model('vision') == 'gpt-4.1-mini'


def test_runtime_policy_aliases_resolve_legacy_model_ids():
    policy = {
        'defaults': {'chat': 'minimax-m2.7'},
        'catalog': [
            {
                'id': 'minimax-m2.7',
                'label': 'MiniMax M2.7',
                'tier': 'economy',
                'enabled': True,
                'visible': True,
                'description': 'upgraded',
                'capabilities': ['chat'],
                'aliases': ['minimax-m2.5'],
            },
            {
                'id': 'gpt-4.1-mini',
                'label': 'GPT-4.1 Mini',
                'tier': 'economy',
                'enabled': True,
                'visible': True,
                'description': 'fallback',
                'capabilities': ['chat'],
            },
        ],
        'profiles': {'economy_chat': ['minimax-m2.7', 'gpt-4.1-mini']},
        'sceneProfiles': {'chat': 'economy_chat'},
        'modelProfileOverrides': {'minimax-m2.7': 'economy_chat'},
    }

    apply_runtime_model_policy(policy)

    assert resolve_model_id('minimax-m2.5') == 'minimax-m2.7'
    assert get_fallback_chain('minimax-m2.5', scene='chat') == ['minimax-m2.7', 'gpt-4.1-mini']
    meta = get_model_runtime_meta('minimax-m2.5', scene='chat')
    assert meta['source'] == 'runtime-policy'
    assert meta['profile'] == 'economy_chat'
