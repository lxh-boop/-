from __future__ import annotations

import json

from agent.communication import AgentMessage, MessageBus, MessageStore, MessageType


def test_message_store_save_load_list_and_sanitize_secret(tmp_path) -> None:
    store = MessageStore(output_dir=tmp_path)
    message = AgentMessage(
        message_id="msg_store_1",
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        sender="write_gateway",
        receiver="ui",
        message_type=MessageType.APPROVAL_REQUESTED,
        payload={
            "plan_id": "plan1",
            "confirmation_token": "raw-token",
            "db_path": "D:/secret/agent_quant.db",
            "summary": "proposal",
        },
        metadata={"user_id": "u1"},
    )

    saved = store.save_message(message)
    loaded = store.load_message("msg_store_1", run_id="run1", user_id="u1")
    by_run = store.list_messages_by_run("run1", user_id="u1")
    by_conv = store.list_messages_by_conversation("conv1", user_id="u1")
    by_task = store.list_messages_by_task("task1", run_id="run1", user_id="u1")
    raw_text = (tmp_path / "message_logs" / "u1" / "run1.jsonl").read_text(encoding="utf-8")

    assert saved.message_id == "msg_store_1"
    assert loaded is not None
    assert len(by_run) == 1
    assert len(by_conv) == 1
    assert len(by_task) == 1
    assert "raw-token" not in raw_text
    assert "agent_quant.db" not in raw_text
    assert "***" in raw_text


def test_message_bus_publish_writes_store_dedupes_and_dispatches_noop(tmp_path) -> None:
    store = MessageStore(output_dir=tmp_path)
    bus = MessageBus(store=store)
    message = AgentMessage(
        message_id="msg_publish_1",
        run_id="run1",
        sender="user",
        receiver="executor",
        message_type=MessageType.USER_REQUEST,
        payload={"query": "hello"},
        metadata={"user_id": "u1"},
    )

    envelope1 = bus.publish(message)
    envelope2 = bus.publish(message)
    dispatch_result = bus.dispatch(envelope1)
    path = tmp_path / "message_logs" / "u1" / "run1.jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert envelope1.message.message_id == "msg_publish_1"
    assert envelope2.message.message_id == "msg_publish_1"
    assert dispatch_result == []
    assert len(lines) == 1


def test_message_bus_dispatch_error_creates_error_message(tmp_path) -> None:
    store = MessageStore(output_dir=tmp_path)
    bus = MessageBus(store=store)

    def failing_handler(message: AgentMessage) -> None:
        raise RuntimeError("handler failed")

    bus.subscribe(MessageType.USER_REQUEST, failing_handler)
    envelope = bus.publish(
        AgentMessage(
            message_id="msg_dispatch_1",
            run_id="run1",
            sender="user",
            receiver="executor",
            message_type=MessageType.USER_REQUEST,
            payload={"query": "hello"},
            metadata={"user_id": "u1"},
        )
    )

    results = bus.dispatch(envelope)
    messages = store.list_messages_by_run("run1", user_id="u1")
    raw_text = (tmp_path / "message_logs" / "u1" / "run1.jsonl").read_text(encoding="utf-8")

    assert len(results) == 1
    assert isinstance(results[0], AgentMessage)
    assert any(message.message_type == MessageType.ERROR_RAISED for message in messages)
    assert "handler failed" in raw_text
    assert json.loads(raw_text.splitlines()[-1])["message"]["message_type"] == "ERROR_RAISED"

