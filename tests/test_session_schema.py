from __future__ import annotations

import json
from pathlib import Path

from lemonclaw.gateway.webui.message_schema import serialize_ui_message
from lemonclaw.session.manager import SessionManager


def test_session_jsonl_round_trips_native_ui_message(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.get_or_create('webui:test')

    session.messages.append(serialize_ui_message({
        'role': 'user',
        'content': '请看附件',
        'media': ['/home/lemonclaw/.lemonclaw/media/demo.jpg'],
        'timestamp': '2026-03-08T12:00:00',
    }))
    session.messages.append(serialize_ui_message({
        'role': 'assistant',
        'content': '模型已切换',
        'metadata': {
            '_ui_notice_text': '/model gpt-5.2',
            '_ui_notice_kind': 'model_switched',
            '_ui_notice_level': 'info',
        },
        'media': ['/home/lemonclaw/.lemonclaw/media/demo.jpg'],
        'timestamp': '2026-03-08T12:00:01',
    }))
    mgr.save(session)

    mgr.invalidate('webui:test')
    reloaded = mgr.get_or_create('webui:test')

    assert len(reloaded.messages) == 2
    assistant = reloaded.messages[1]
    assert assistant['media'][0]['filename'] == 'demo.jpg'
    assert any(block['type'] == 'system_notice' for block in assistant['blocks'])
    assert any(block['type'] == 'media' for block in assistant['blocks'])


def test_session_jsonl_file_contains_blocks_and_media(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.get_or_create('webui:test-file')
    session.messages.append(serialize_ui_message({
        'role': 'assistant',
        'content': '附件如下',
        'media': [
            '/home/lemonclaw/.lemonclaw/media/demo.jpg',
            '/home/lemonclaw/.lemonclaw/media/note.ogg',
        ],
        'timestamp': '2026-03-08T12:00:00',
    }))
    mgr.save(session)

    path = mgr._get_session_path('webui:test-file')
    lines = path.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 2  # metadata + 1 message
    raw = json.loads(lines[1])
    assert raw['role'] == 'assistant'
    assert isinstance(raw['media'], list) and len(raw['media']) == 2
    assert isinstance(raw['blocks'], list) and len(raw['blocks']) >= 2
    assert {block['type'] for block in raw['blocks']} >= {'markdown', 'media'}


def test_session_get_history_remains_llm_friendly_with_native_blocks(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.get_or_create('webui:test-history')
    session.messages.append(serialize_ui_message({
        'role': 'user',
        'content': '先看图片',
        'media': ['/home/lemonclaw/.lemonclaw/media/demo.jpg'],
    }))
    session.messages.append(serialize_ui_message({
        'role': 'assistant',
        'content': '好的',
        'metadata': {
            '_ui_notice_text': '/help',
            '_ui_notice_kind': 'help',
        },
    }))

    history = session.get_history()
    assert history == [
        {'role': 'user', 'content': '先看图片'},
        {'role': 'assistant', 'content': '好的'},
    ]
