from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import urlopen
from uuid import uuid4

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

PAGES = [
    "\u9996\u9875 / \u9884\u6d4b\u6392\u540d",
    "AI Agent",
    "AI \u6a21\u62df\u76d8",
    "\u7cfb\u7edf\u76d1\u63a7",
]


def _health(url: str = "http://127.0.0.1:8501/_stcore/health") -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8", errors="replace")


def _page_check(page_name: str) -> dict[str, object]:
    at = AppTest.from_file(str(ROOT / "app.py"))
    at.run(timeout=60)
    at.radio[0].set_value(page_name).run(timeout=90)
    text = "\n".join(str(item.value) for item in [*at.markdown, *at.caption])
    forbidden = ["confirmation_token", "agent_quant.db", "Traceback (most recent call last)"]
    return {
        "page": page_name,
        "exceptions": len(at.exception),
        "error_count": len(at.error),
        "contains_forbidden": any(item in text for item in forbidden),
    }


def _fake_run_agent(
    query: str,
    *,
    user_id: str,
    output_dir: str,
    db_path: str | None,
    default_topk: int,
    session_id: str,
) -> dict[str, object]:
    del db_path, default_topk
    from agent.communication import AgentMessage, MessageStore, MessageType
    from agent.react import ObservationEvent, ObservationType, ObserveStore

    run_id = f"phase15_{uuid4().hex[:10]}"
    ObserveStore(output_dir=output_dir).save_observation(
        ObservationEvent(
            conversation_id=session_id,
            run_id=run_id,
            task_id="task_1",
            source_tool_name="phase15.fake",
            observation_type=ObservationType.TOOL_SUCCESS,
            summary=f"phase15 safe observation for {query}",
        ),
        user_id=user_id,
    )
    message_store = MessageStore(output_dir=output_dir)
    for message_type, summary in (
        (MessageType.OBSERVATION_CREATED, "observation created"),
        (MessageType.REPLAN_SKIPPED, "no replan needed"),
        (MessageType.FINAL_REPORT, "final report ready"),
    ):
        message_store.save_message(
            AgentMessage(
                conversation_id=session_id,
                run_id=run_id,
                sender="phase15_fake",
                receiver="ai_agent_ui",
                message_type=message_type,
                payload={"summary": summary, "user_id": user_id},
                metadata={"user_id": user_id},
            )
        )
    return {
        "success": True,
        "run_id": run_id,
        "runtime": {"run_id": run_id, "status": "completed"},
        "answer": f"Phase 15 test answer: {query}",
        "context": {
            "phase12_context": {
                "minimal_context": {"context_id": f"ctx_{run_id}", "run_id": run_id},
                "llm_context": {"context_id": f"ctx_{run_id}", "run_id": run_id},
            }
        },
        "orchestration": {"task_results": {"task_1": {"intent": "phase15_ui", "status": "success"}}},
        "tool_calls": [{"task_id": "task_1", "tool_name": "phase15.fake", "success": True}],
    }


def _long_chat_check(temp_root: Path) -> dict[str, object]:
    import app.pages.ai_agent as ai_agent

    output_dir = temp_root / "outputs"
    db_path = temp_root / "agent_ui.db"
    app_source = f"""
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path({json.dumps(str(ROOT))})
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.pages.ai_agent as ai_agent
from agent.communication import AgentMessage, MessageStore, MessageType
from agent.react import ObservationEvent, ObservationType, ObserveStore

OUTPUT_DIR = {json.dumps(str(output_dir))}
DB_PATH = {json.dumps(str(db_path))}


def fake_run_agent(query, *, user_id, output_dir, db_path, default_topk, session_id):
    del db_path, default_topk
    run_id = f"phase15_{{uuid4().hex[:10]}}"
    ObserveStore(output_dir=output_dir).save_observation(
        ObservationEvent(
            conversation_id=session_id,
            run_id=run_id,
            task_id="task_1",
            source_tool_name="phase15.fake",
            observation_type=ObservationType.TOOL_SUCCESS,
            summary=f"phase15 safe observation for {{query}}",
        ),
        user_id=user_id,
    )
    store = MessageStore(output_dir=output_dir)
    for message_type, summary in (
        (MessageType.OBSERVATION_CREATED, "observation created"),
        (MessageType.REPLAN_SKIPPED, "no replan needed"),
        (MessageType.FINAL_REPORT, "final report ready"),
    ):
        store.save_message(
            AgentMessage(
                conversation_id=session_id,
                run_id=run_id,
                sender="phase15_fake",
                receiver="ai_agent_ui",
                message_type=message_type,
                payload={{"summary": summary, "user_id": user_id}},
                metadata={{"user_id": user_id}},
            )
        )
    return {{
        "success": True,
        "run_id": run_id,
        "runtime": {{"run_id": run_id, "status": "completed"}},
        "answer": f"Phase 15 test answer: {{query}}",
        "context": {{
            "phase12_context": {{
                "minimal_context": {{"context_id": f"ctx_{{run_id}}", "run_id": run_id}},
                "llm_context": {{"context_id": f"ctx_{{run_id}}", "run_id": run_id}},
            }}
        }},
        "orchestration": {{"task_results": {{"task_1": {{"intent": "phase15_ui", "status": "success"}}}}}},
        "tool_calls": [{{"task_id": "task_1", "tool_name": "phase15.fake", "success": True}}],
    }}


ai_agent._run_agent = fake_run_agent
ai_agent.render_ai_agent_page(
    user_id="phase15_web",
    output_dir=OUTPUT_DIR,
    db_path=DB_PATH,
    default_topk=3,
)
"""
    try:
        at = AppTest.from_string(app_source)
        at.run(timeout=60)
        questions = [
            "\u67e5\u770b\u6211\u7684\u5f53\u524d\u6301\u4ed3",
            "\u5206\u6790\u5f53\u524d\u7ec4\u5408\u98ce\u9669",
            "\u7ed9\u6211\u4e00\u4e2a\u8c03\u4ed3\u5efa\u8bae",
            "\u67e5\u770b\u6700\u65b0\u62a5\u544a",
            "\u67e5\u770b\u7cfb\u7edf\u72b6\u6001",
            "\u6211\u4e0a\u6b21\u4e3a\u4ec0\u4e48\u5efa\u8bae\u8c03\u4ed3\uff1f",
        ]
        questions.extend(f"phase15 long chat {index}" for index in range(6))
        for question in questions:
            at.chat_input[0].set_value(question).run(timeout=90)

        message_key = ai_agent._messages_key("phase15_web")
        visible_count_before = len(_session_get(at, message_key, []) or [])
        text_before = "\n".join(str(getattr(item, "value", "")) for item in [*at.markdown, *at.caption, *at.json])
        default_window_ok = visible_count_before <= ai_agent.PHASE15_VISIBLE_MESSAGE_WINDOW
        load_key = (
            f"ai_agent_phase15_load_earlier::phase15_web::"
            f"{_session_get(at, ai_agent._session_key('phase15_web'), '')}::10"
        )
        try:
            load_button = at.button(key=load_key)
            load_button_available = True
        except Exception:
            load_button = None
            load_button_available = False
        if load_button_available:
            load_button.click().run(timeout=90)
        visible_count_after = len(_session_get(at, message_key, []) or [])
        text_after = "\n".join(str(getattr(item, "value", "")) for item in [*at.markdown, *at.caption, *at.json])
        combined_text = text_before + "\n" + text_after
        forbidden = ["confirmation_token", "agent_quant.db", "raw_tool_payload", "Traceback (most recent call last)"]
        return {
            "exceptions": len(at.exception),
            "error_count": len(at.error),
            "visible_count_before": visible_count_before,
            "visible_count_after": visible_count_after,
            "default_window_ok": default_window_ok,
            "load_button_available": load_button_available,
            "load_button_increased_window": visible_count_after > visible_count_before,
            "react_caption_visible": "ReAct trace:" in combined_text,
            "memory_summary_visible": "Memory safe summary" in combined_text,
            "contains_forbidden": any(item in combined_text for item in forbidden),
        }
    except Exception as exc:
        return {
            "exceptions": 1,
            "error_count": 1,
            "visible_count_before": 0,
            "visible_count_after": 0,
            "default_window_ok": False,
            "load_button_available": False,
            "load_button_increased_window": False,
            "react_caption_visible": False,
            "memory_summary_visible": False,
            "contains_forbidden": False,
            "script_error": type(exc).__name__,
            "script_error_message": str(exc)[:200],
        }


def _session_get(at: AppTest, key: str, default: object = None) -> object:
    try:
        return at.session_state[key]
    except Exception:
        return default


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="phase15_react_loading_"))
    try:
        result = {
            "health": _health(),
            "pages": [_page_check(page) for page in PAGES],
            "long_chat": _long_chat_check(temp_root),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        failed = result["health"] != "ok"
        failed = failed or any(item["exceptions"] or item["error_count"] or item["contains_forbidden"] for item in result["pages"])
        failed = failed or bool(result["long_chat"]["exceptions"] or result["long_chat"]["error_count"])
        failed = failed or not result["long_chat"]["default_window_ok"]
        failed = failed or not result["long_chat"]["load_button_available"]
        failed = failed or not result["long_chat"]["load_button_increased_window"]
        failed = failed or not result["long_chat"]["react_caption_visible"]
        failed = failed or not result["long_chat"]["memory_summary_visible"]
        failed = failed or result["long_chat"]["contains_forbidden"]
        return 1 if failed else 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
