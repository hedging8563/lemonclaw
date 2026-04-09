import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from lemonclaw.bus.queue import MessageBus
from lemonclaw.config.schema import SlackConfig
from lemonclaw.triggers import TriggerRuntime

slack_module = pytest.importorskip('lemonclaw.channels.slack', exc_type=ImportError)
SlackChannel = slack_module.SlackChannel


@pytest.mark.asyncio
async def test_slack_dm_pairing_routes_pending_and_approval(tmp_path):
    bus = MessageBus()
    outbound = []

    async def _capture_outbound(msg):
        outbound.append(msg)

    bus.publish_outbound = _capture_outbound  # type: ignore[assignment]

    config = SlackConfig(enabled=True, bot_token='xoxb-test', app_token='xapp-test')
    config.dm.policy = 'pairing'
    channel = SlackChannel(config, bus)
    channel.enable_auto_pairing(tmp_path)

    assert await channel._run_pairing_flow(sender_id='U1', notify_target='D1', content='hello', display_name='U1') is True
    assert await channel._run_pairing_flow(sender_id='U2', notify_target='D2', content='hello', display_name='U2') is False
    assert any(msg.chat_id == 'D1' and 'approve' in (msg.content or '').lower() for msg in outbound)
    assert any(msg.chat_id == 'D2' and 'pending owner approval' in (msg.content or '').lower() for msg in outbound)

    assert await channel._run_pairing_flow(sender_id='U1', notify_target='D1', content='/approve U2', display_name='U1') is False
    assert any(msg.chat_id == 'D2' and 'approved' in (msg.content or '').lower() for msg in outbound)


@pytest.mark.asyncio
async def test_slack_thread_reply_to_bot_counts_as_group_trigger(tmp_path):
    bus = MessageBus()
    config = SlackConfig(enabled=True, bot_token='xoxb-test', app_token='xapp-test')
    config.group_policy = 'mention'
    config.group_require_mention = True
    trigger_runtime = TriggerRuntime(tmp_path)
    channel = SlackChannel(config, bus, trigger_runtime=trigger_runtime)
    channel._bot_user_id = 'BOT123'
    channel._web_client = SimpleNamespace(reactions_add=AsyncMock())
    channel._handle_message = AsyncMock()

    client = SimpleNamespace(send_socket_mode_response=AsyncMock())
    event = {
        'type': 'message',
        'user': 'USER1',
        'channel': 'CH1',
        'channel_type': 'channel',
        'text': '继续',
        'ts': '2000.2',
        'thread_ts': '1000.1',
        'parent_user_id': 'BOT123',
    }
    req = SimpleNamespace(type='events_api', envelope_id='env1', payload={'event': event})

    await channel._on_socket_request(client, req)

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs['session_key'] == 'slack:CH1:1000.1'
    trigger_id = kwargs['metadata']['_trigger_id']
    assert kwargs['metadata']['_trigger_source'] == 'socket.slack'
    assert kwargs['metadata']['_trigger_kind'] == 'message.channel'
    record = trigger_runtime.read_trigger(trigger_id)
    assert record is not None
    assert record['chat_id'] == 'CH1'


@pytest.mark.asyncio
async def test_slack_file_share_message_downloads_attachment(tmp_path, monkeypatch):
    bus = MessageBus()
    config = SlackConfig(enabled=True, bot_token='xoxb-test', app_token='xapp-test')
    channel = SlackChannel(config, bus)
    channel._bot_user_id = 'BOT123'
    channel._web_client = SimpleNamespace(reactions_add=AsyncMock())

    class _FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    class _FakeHttp:
        async def get(self, url, headers=None):
            assert url == 'https://files.slack.com/files-pri/T1-F1/test.docx'
            assert headers == {'Authorization': 'Bearer xoxb-test'}
            return _FakeResponse(b'docx-bytes')

    channel._http = _FakeHttp()
    channel._handle_message = AsyncMock()
    monkeypatch.setattr("lemonclaw.channels.slack.Path.home", lambda: tmp_path)

    client = SimpleNamespace(send_socket_mode_response=AsyncMock())
    event = {
        'type': 'message',
        'subtype': 'file_share',
        'user': 'USER1',
        'channel': 'D1',
        'channel_type': 'im',
        'text': '',
        'ts': '2000.2',
        'files': [
            {
                'id': 'F1',
                'name': 'test.docx',
                'url_private_download': 'https://files.slack.com/files-pri/T1-F1/test.docx',
            }
        ],
    }
    req = SimpleNamespace(type='events_api', envelope_id='env1', payload={'event': event})

    await channel._on_socket_request(client, req)

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert "[attachment:" in kwargs["content"]
    assert kwargs["media"] and kwargs["media"][0].endswith("F1_test.docx")
