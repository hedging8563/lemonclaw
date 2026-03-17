from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from lemonclaw.agent.loop import AgentLoop
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.wecom import WeComChannel, WeComCrypto, verify_signature
from lemonclaw.config.schema import WeComConfig
from lemonclaw.config.schema import Config
from lemonclaw.gateway.server import create_app
from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.session.manager import SessionManager
from lemonclaw.triggers import build_trigger_metadata
from lemonclaw.triggers import TriggerRuntime


def test_trigger_runtime_roundtrip(tmp_path: Path):
    runtime = TriggerRuntime(tmp_path)

    trigger = runtime.record_trigger(
        source="cron",
        kind="agent_turn",
        payload_summary="check inbox",
        session_key="cron:job-1",
        channel="cli",
        chat_id="direct",
        metadata={"job_id": "job-1"},
    )
    linked = runtime.link_task(trigger["trigger_id"], task_id="task_1", session_key="cron:job-1")
    finished = runtime.finish_trigger(
        trigger["trigger_id"],
        status="completed",
        result_summary="done",
        metadata={"task_status": "completed"},
    )

    assert linked is not None
    assert finished is not None
    assert finished["task_id"] == "task_1"
    assert finished["status"] == "completed"
    listed = runtime.list_triggers(limit=10)
    assert listed[0]["trigger_id"] == trigger["trigger_id"]
    summary = runtime.summarize_triggers(limit=10)
    assert summary["by_source"]["cron"] == 1
    assert summary["by_status"]["completed"] == 1


def test_agent_loop_process_direct_links_trigger_to_task(tmp_path: Path, echo_provider) -> None:
    trigger_runtime = TriggerRuntime(tmp_path)
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=echo_provider,
        workspace=tmp_path,
        model="test-model",
        max_iterations=4,
        memory_window=20,
        trigger_runtime=trigger_runtime,
    )
    trigger = trigger_runtime.record_trigger(
        source="cron",
        kind="agent_turn",
        payload_summary="say hello",
        session_key="cron:job-1",
        channel="cli",
        chat_id="direct",
    )

    result = __import__("asyncio").run(
        loop.process_direct(
            "hello from trigger",
            session_key="cron:job-1",
            channel="cron",
            chat_id="direct",
            metadata=build_trigger_metadata(trigger),
        )
    )

    assert result.startswith("Echo:")
    triggers = trigger_runtime.list_triggers(limit=10)
    assert triggers[0]["trigger_id"] == trigger["trigger_id"]
    assert triggers[0]["status"] == "completed"
    assert triggers[0]["task_id"].startswith("task_")
    task = loop.ledger.read_task(triggers[0]["task_id"])
    assert task is not None
    assert task["metadata"]["trigger"]["trigger_id"] == trigger["trigger_id"]


def test_trigger_api_lists_and_reads_records(tmp_path: Path) -> None:
    trigger_runtime = TriggerRuntime(tmp_path)
    trigger = trigger_runtime.record_trigger(
        source="heartbeat",
        kind="heartbeat.run",
        payload_summary="check tasks",
        session_key="heartbeat",
        channel="cli",
        chat_id="direct",
    )
    app = create_app(
        auth_token=None,
        agent_loop=SimpleNamespace(workspace=tmp_path),
        session_manager=SessionManager(tmp_path),
        trigger_runtime=trigger_runtime,
        webui_enabled=True,
    )
    client = TestClient(app)

    list_resp = client.get("/api/triggers")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["summary"]["by_source"]["heartbeat"] == 1
    assert data["triggers"][0]["trigger_id"] == trigger["trigger_id"]

    detail_resp = client.get(f"/api/triggers/{trigger['trigger_id']}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["trigger"]["kind"] == "heartbeat.run"


def test_trigger_bundle_includes_linked_task_bundle(tmp_path: Path) -> None:
    trigger_runtime = TriggerRuntime(tmp_path)
    ledger = TaskLedger(tmp_path)
    trigger = trigger_runtime.record_trigger(
        source="cron",
        kind="agent_turn",
        payload_summary="bundle me",
        session_key="cron:job-1",
        channel="cron",
        chat_id="direct",
    )
    trigger_runtime.link_task(trigger["trigger_id"], task_id="task_bundle", session_key="cron:job-1")
    ledger.ensure_task(
        task_id="task_bundle",
        session_key="cron:job-1",
        agent_id="default",
        mode="chat",
        channel="cron",
        goal="bundle me",
        metadata={"trigger": {"trigger_id": trigger["trigger_id"], "source": trigger["source"], "kind": trigger["kind"]}},
    )

    app = create_app(
        auth_token=None,
        agent_loop=SimpleNamespace(workspace=tmp_path, ledger=ledger, trigger_runtime=trigger_runtime),
        session_manager=SessionManager(tmp_path),
        trigger_runtime=trigger_runtime,
        webui_enabled=True,
    )
    client = TestClient(app)

    resp = client.get(f"/api/triggers/{trigger['trigger_id']}/bundle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trigger"]["trigger_id"] == trigger["trigger_id"]
    assert data["task_bundle"]["task"]["task_id"] == "task_bundle"
    assert data["task_bundle"]["trigger"]["trigger_id"] == trigger["trigger_id"]


@pytest.mark.asyncio
async def test_wecom_event_trigger_is_recorded(tmp_path: Path) -> None:
    trigger_runtime = TriggerRuntime(tmp_path)
    channel = WeComChannel(WeComConfig(), MessageBus(), trigger_runtime=trigger_runtime)

    await channel._process_message(  # type: ignore[attr-defined]
        {
            "MsgType": "event",
            "FromUserName": "user-1",
            "Event": "subscribe",
            "EventKey": "key-1",
        }
    )

    records = trigger_runtime.list_triggers(limit=10)
    assert records[0]["source"] == "webhook.wecom"
    assert records[0]["kind"] == "wecom.event.subscribe"


@pytest.mark.asyncio
async def test_wecom_verify_trigger_is_recorded(tmp_path: Path) -> None:
    trigger_runtime = TriggerRuntime(tmp_path)
    cfg = WeComConfig(
        corp_id="wx1234567890abcdef",
        token="tok",
        encoding_aes_key="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
    )
    channel = WeComChannel(cfg, MessageBus(), trigger_runtime=trigger_runtime)
    channel._crypto = WeComCrypto(cfg.encoding_aes_key, cfg.corp_id)

    echostr = channel._crypto.encrypt("hello")
    params = {
        "timestamp": "123",
        "nonce": "abc",
        "echostr": echostr,
        "msg_signature": verify_signature(cfg.token, "123", "abc", echostr),
    }

    result = await channel.handle_verify(params)

    assert result == "hello"
    records = trigger_runtime.list_triggers(limit=10)
    assert records[0]["kind"] == "wecom.verify"
