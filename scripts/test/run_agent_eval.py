from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.agent_core import run_agent
from agent.intent_router import route_intent
from core.config.paths import OUTPUTS_DIR, ROOT_DIR


QUESTIONS_PATH = ROOT_DIR / "tests" / "fixtures" / "agent_questions.csv"
REPORT_PATH = OUTPUTS_DIR / "test_reports" / "agent_eval_report.md"


def main() -> None:
    rows = list(csv.DictReader(QUESTIONS_PATH.open("r", encoding="utf-8-sig")))
    intent_hits = 0
    tool_hits = 0
    answer_hits = 0
    failures = []

    for row in rows:
        question = row["question"]
        expected_intent = row["expected_intent"]
        expected_tool = row["expected_tool"]
        actual_intent = route_intent(question)
        if actual_intent == expected_intent:
            intent_hits += 1

        response = run_agent(question, topk=5)
        actual_tool = response.tool_calls[0].tool_name if response.tool_calls else ""
        if actual_tool == expected_tool:
            tool_hits += 1
        if response.answer and "不构成投资建议" in response.answer:
            answer_hits += 1

        if actual_intent != expected_intent or actual_tool != expected_tool:
            failures.append(
                {
                    "question": question,
                    "expected_intent": expected_intent,
                    "actual_intent": actual_intent,
                    "expected_tool": expected_tool,
                    "actual_tool": actual_tool,
                }
            )

    total = max(len(rows), 1)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Agent 评估报告",
        "",
        f"- 测试问题数：{len(rows)}",
        f"- 意图识别准确率：{intent_hits / total:.2%}",
        f"- 工具调用匹配率：{tool_hits / total:.2%}",
        f"- 回答成功率：{answer_hits / total:.2%}",
        "",
        "## 失败样例",
    ]
    if failures:
        for item in failures:
            lines.append(
                f"- {item['question']}：intent {item['actual_intent']} / {item['expected_intent']}，"
                f"tool {item['actual_tool']} / {item['expected_tool']}"
            )
    else:
        lines.append("暂无。")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT_PATH)


if __name__ == "__main__":
    main()
