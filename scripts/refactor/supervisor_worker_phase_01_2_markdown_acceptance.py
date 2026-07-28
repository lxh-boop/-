"""Deterministic acceptance for the complete Agent-run Markdown archive."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import console_trace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="phase_01_2_markdown_") as temp_dir:
        os.environ["AGENT_FLOW_TRACE"] = "1"
        os.environ["AGENT_FLOW_MARKDOWN_DIR"] = temp_dir
        console_trace._RUN_FILES.clear()
        console_trace._RUN_SEQUENCE.clear()
        console_trace._RUN_FINALIZED.clear()
        console_trace.reset_flow_context()

        run_id = "phase_01_2_acceptance_run"
        console_trace.flow_event(
            "GRAPH_REQUEST",
            {"raw_message": "分析已确认金融实体", "user_id": "acceptance"},
            run_id=run_id,
        )
        execution = {
            "execution_status": "completed",
            "internal_tool_call_count": 1,
            "task_results": {
                "W01_001": {
                    "task_id": "W01_001",
                    "agent_id": "EVIDENCE_RETRIEVER",
                    "status": "completed",
                    "output_type": "EntityResearchResult",
                    "summary": "实体研究完成。",
                    "data": {
                        "entity_refs": [{"node_id": "object:security:600519"}],
                        "research_question": "分析已确认金融实体",
                        "results": [],
                    },
                    "confidence": 0.8,
                    "evidence_refs": [],
                    "artifact_refs": [],
                    "metadata": {
                        "duration_ms": 100,
                        "tool_execution": {"tool_name": "graph.evidence.analyze_entities"},
                    },
                },
                "W06_001": {
                    "task_id": "W06_001",
                    "agent_id": "REPORT_WRITER",
                    "status": "completed",
                    "output_type": "FinalReport",
                    "summary": "最终报告。",
                    "data": {
                        "language": "zh",
                        "source_task_ids": ["W01_001"],
                        "content": "最终报告。",
                        "limitations": [],
                    },
                    "confidence": 0.8,
                    "evidence_refs": [],
                    "artifact_refs": [],
                    "metadata": {"duration_ms": 200},
                },
            },
            "graph_worker_results": {
                "task_count": 2,
                "completed_count": 2,
                "failed_count": 0,
                "waiting_context_count": 0,
            },
            "execution_batches": [
                {"batch_index": 1, "task_ids": ["W01_001"], "agents": ["EVIDENCE_RETRIEVER"], "parallel": False},
                {"batch_index": 2, "task_ids": ["W06_001"], "agents": ["REPORT_WRITER"], "parallel": False},
            ],
            "warnings": [],
            "errors": [],
            "graph_runtime": {
                "planner": {
                    "worker_selection_owner": "main_agent",
                    "dag_mutation_after_planning": "forbidden",
                },
                "worker_dag": {
                    "contract_version": "worker_dag_snapshot.v1",
                    "task_count": 2,
                    "tasks": [
                        {
                            "task_id": "W01_001",
                            "worker_id": "W01",
                            "assigned_agent": "EVIDENCE_RETRIEVER",
                            "task_type": "analyze_entity_evidence",
                            "objective": "完成实体研究",
                            "args": {"focus_ref_ids": ["object:security:600519"], "research_question": "分析已确认金融实体"},
                            "dependency_task_ids": [],
                            "expected_output_type": "EntityResearchResult",
                            "constraints": ["read_only"],
                            "status": "ready",
                        },
                        {
                            "task_id": "W06_001",
                            "worker_id": "W06",
                            "assigned_agent": "REPORT_WRITER",
                            "task_type": "write_report",
                            "objective": "生成最终报告",
                            "args": {"input_task_ids": ["W01_001"], "report_goal": "回答用户问题", "reply_language": "zh"},
                            "dependency_task_ids": ["W01_001"],
                            "expected_output_type": "FinalReport",
                            "constraints": [],
                            "status": "created",
                        },
                    ],
                },
                "focus_refs": [{"node_id": "object:security:600519"}],
            },
        }
        markdown_path = Path(
            console_trace.finalize_flow_markdown(
                run_id=run_id,
                question="分析已确认金融实体",
                execution=execution,
                runtime_status="completed",
                success=True,
                final_answer="最终报告。",
                user_id="acceptance",
                session_id="acceptance-session",
                language="zh",
                llm_runtime={"model_name": "acceptance-model", "api_key": "must-not-leak"},
            )
        )
        content = markdown_path.read_text(encoding="utf-8")
        required = [
            "# 运行总览",
            "## MainAgent 规划信息",
            "## Worker DAG",
            "W01_001",
            "W06_001",
            "## 执行批次",
            "## Worker 执行结果",
            "私有 Tool 执行摘要",
            "## 已解析 GraphRef",
            "## 最终回答",
            "最终报告。",
        ]
        missing = [item for item in required if item not in content]
        if missing:
            raise AssertionError("missing_markdown_sections:" + ",".join(missing))
        if "must-not-leak" in content:
            raise AssertionError("secret_leaked_to_markdown")

        report = {
            "phase": "01.2",
            "status": "passed",
            "markdown_sections": required,
            "secret_redaction": True,
            "main_agent_worker_dag_preserved": True,
            "worker_result_details_saved": True,
            "final_answer_saved": True,
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
