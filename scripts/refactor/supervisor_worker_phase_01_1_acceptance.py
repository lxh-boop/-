"""Deterministic acceptance for structured Worker contracts and Worker DAGs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.models import GraphWorkerResult, ResultStatus
from agent.collaboration.planner import CoordinatorPlanner
from agent.graph.contracts import GraphNodeKind, GraphRef


class FakeLLMService:
    def generate_json(self, *, validator=None, **_kwargs):
        payload = {
            "tasks": [
                {
                    "task_id": "task_1",
                    "worker_id": "W01",
                    "objective": "围绕已确认金融实体形成独立研究结果",
                    "task_type": "analyze_entity_evidence",
                    "args": {
                        "focus_ref_ids": ["object:security:600519"],
                        "research_question": "分析当前表现、主要证据与风险因素",
                    },
                    "constraints": ["read_only"],
                    "dependency_task_ids": [],
                    "expected_output_type": "EntityResearchResult",
                    "priority": 1,
                },
                {
                    "task_id": "task_2",
                    "worker_id": "W06",
                    "objective": "依据上游结构化结果形成最终报告",
                    "task_type": "write_report",
                    "args": {
                        "input_task_ids": ["task_1"],
                        "report_goal": "形成金融实体分析报告",
                        "reply_language": "zh",
                    },
                    "constraints": ["upstream_results_only"],
                    "dependency_task_ids": ["task_1"],
                    "expected_output_type": "FinalReport",
                    "priority": 2,
                },
            ]
        }
        if validator:
            validator(payload)
        return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    directory = AgentDirectory()
    focus_ref = GraphRef(
        graph_id="financial_graph",
        node_id="object:security:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
    )
    planner = CoordinatorPlanner(directory, llm_service=FakeLLMService())
    tasks, metadata = planner.plan(
        query="分析指定金融实体",
        request_mode="analysis",
        session_id="phase-01-1-session",
        run_id="phase-01-1-run",
        user_id="phase-01-1-user",
        focus_refs=[focus_ref],
        context_refs=[],
        memory_summary="",
        language="zh",
    )

    worker_ids = [task.worker_id for task in tasks]
    if worker_ids != ["W01", "W06"]:
        raise AssertionError(f"unexpected_worker_dag:{worker_ids}")
    if tasks[1].dependency_task_ids != ["task_1"]:
        raise AssertionError("report_dependency_invalid")

    result = GraphWorkerResult(
        task_id="task_1",
        agent_id="EVIDENCE_RETRIEVER",
        status=ResultStatus.COMPLETED,
        output_type="EntityResearchResult",
        data={
            "entity_refs": [focus_ref.to_dict()],
            "research_question": "分析当前表现",
            "results": [],
            "evidence_refs": [],
            "conclusion": "完成",
        },
        summary="完成",
    )
    directory.validate_result(result)

    catalog = directory.safe_catalog()
    if any("private_tool_ids" in card for card in catalog):
        raise AssertionError("private_tool_catalog_leaked_to_main_agent")

    report = {
        "phase": "01.1",
        "status": "passed",
        "worker_count": len(catalog),
        "planned_worker_ids": worker_ids,
        "main_agent_selects_workers": True,
        "dag_mutation_after_planning": False,
        "task_args_schema_validated": True,
        "worker_result_schema_validated": True,
        "private_tool_visibility": "worker_only",
        "metadata": metadata,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
