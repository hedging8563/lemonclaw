import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.config.schema import SlackConfig

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
    assert outbound[-1].chat_id == 'D1'

    assert await channel._run_pairing_flow(sender_id='U1', notify_target='D1', content='/approve U2', display_name='U1') is False
    assert any(msg.chat_id == 'D2' and 'approved' in (msg.content or '').lower() for msg in outbound)
