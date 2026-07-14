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

import app.pages.ai_agent as ai_agent

PAGES = [
    "首页 / 预测排名",
    "AI Agent",
    "AI 模拟盘",
    "系统监控",
]
FORBIDDEN = [
    "confirmation_token",
    "agent_quant.db",
    "raw_tool_payload",
    "raw_positions",
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "NameError",
    "KeyError",
]


def _health(url: str = "http://127.0.0.1:8501/_stcore/health") -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8", errors="replace")


def _page_check(page_name: str) -> dict[str, object]:
    at = AppTest.from_file(str(ROOT / "app.py"))
    at.run(timeout=60)
    at.radio[0].set_value(page_name).run(timeout=90)
    text = "\n".join(str(item.value) for item in [*at.markdown, *at.caption, *at.subheader])
    return {
        "page": page_name,
        "exceptions": len(at.exception),
        "error_count": len(at.error),
        "contains_forbidden": any(item in text for item in FORBIDDEN),
    }


def _reflection_ai_agent_check(temp_root: Path) -> dict[str, object]:
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
from agent.reflection import CriticAction, CriticResult, ReflectionStore

OUTPUT_DIR = {json.dumps(str(output_dir))}
DB_PATH = {json.dumps(str(db_path))}


def fake_run_agent(query, *, user_id, output_dir, db_path, default_topk, session_id):
    del db_path, default_topk
    run_id = f"phase16_{{uuid4().hex[:10]}}"
    critic = CriticResult(
        conversation_id=session_id,
        run_id=run_id,
        task_id="task_1",
        action=CriticAction.PASS,
        target_summary=f"safe reflection for {{query}}",
        evidence_refs=[{{"artifact_id": "artifact_safe"}}],
    )
    ReflectionStore(output_dir=output_dir).save_result(critic, user_id=user_id)
    store = MessageStore(output_dir=output_dir)
    for message_type, payload in (
        (MessageType.REFLECTION_REQUESTED, {{"summary": "reflection requested"}}),
        (MessageType.REFLECTION_RESULT, {{"critic_id": critic.critic_id, "action": "PASS", "issue_count": 0}}),
        (MessageType.FINAL_REPORT, {{"summary": "final report ready"}}),
    ):
        store.save_message(
            AgentMessage(
                conversation_id=session_id,
                run_id=run_id,
                sender="phase16_fake",
                receiver="ai_agent_ui",
                message_type=message_type,
                payload=payload,
                metadata={{"user_id": user_id}},
            )
        )
    return {{
        "success": True,
        "run_id": run_id,
        "runtime": {{"run_id": run_id, "status": "completed"}},
        "answer": f"Phase 16 reflection answer: {{query}}",
        "reflection": {{
            "critic_id": critic.critic_id,
            "action": "PASS",
            "severity": "INFO",
            "score": 1.0,
            "issue_count": 0,
            "summary": "safe reflection for UI",
            "evidence_refs": [{{"artifact_id": "artifact_safe"}}],
        }},
        "context": {{
            "phase12_context": {{
                "minimal_context": {{"context_id": f"ctx_{{run_id}}", "run_id": run_id}},
                "llm_context": {{"context_id": f"ctx_{{run_id}}", "run_id": run_id}},
            }}
        }},
        "orchestration": {{"task_results": {{"task_1": {{"intent": "phase16_ui", "status": "success"}}}}}},
        "tool_calls": [{{"task_id": "task_1", "tool_name": "phase16.fake", "success": True}}],
    }}


ai_agent._run_agent = fake_run_agent
ai_agent.render_ai_agent_page(
    user_id="phase16_web",
    output_dir=OUTPUT_DIR,
    db_path=DB_PATH,
    default_topk=3,
)
"""
    at = AppTest.from_string(app_source)
    at.run(timeout=60)
    questions = ["查看当前模拟盘持仓", "分析当前组合风险"]
    for question in questions:
        at.chat_input[0].set_value(question).run(timeout=90)
    text = "\n".join(str(getattr(item, "value", "")) for item in [*at.markdown, *at.caption, *at.json])
    message_key = ai_agent._messages_key("phase16_web")
    try:
        visible_count = len(at.session_state[message_key] or [])
    except Exception:
        visible_count = 0
    return {
        "exceptions": len(at.exception),
        "error_count": len(at.error),
        "reflection_summary_visible": "Reflection Critic:" in text,
        "critic_action_seen": "action=PASS" in text,
        "long_chat_window_ok": visible_count <= ai_agent.PHASE15_VISIBLE_MESSAGE_WINDOW,
        "contains_forbidden": any(item in text for item in FORBIDDEN),
    }


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="phase16_reflection_web_"))
    try:
        result = {
            "health": _health(),
            "pages": [_page_check(page) for page in PAGES],
            "ai_agent_reflection": _reflection_ai_agent_check(temp_root),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        failed = result["health"] != "ok"
        failed = failed or any(item["exceptions"] or item["error_count"] or item["contains_forbidden"] for item in result["pages"])
        ai = result["ai_agent_reflection"]
        failed = failed or bool(ai["exceptions"] or ai["error_count"] or ai["contains_forbidden"])
        failed = failed or not ai["reflection_summary_visible"]
        failed = failed or not ai["critic_action_seen"]
        failed = failed or not ai["long_chat_window_ok"]
        return 1 if failed else 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
