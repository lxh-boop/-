from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.planner import CoordinatorPlanner
from agent.graph.contracts import GraphNodeKind, GraphRef


class FakeLLM:
    def generate_json(self, *, validator=None, **_: object) -> dict:
        payload = {
            "tasks": [
                {
                    "task_id": "W01_001",
                    "worker_id": "W01",
                    "objective": "形成已解析金融实体的结构化研究结果",
                    "task_type": "retrieve_evidence",
                    "args": {
                        "research_question": "分析当前表现和主要风险因素"
                    },
                    "inputs": {
                        "focus_ref_ids": ["cn:security:sse:600519"]
                    },
                    "constraints": ["read_only"],
                    "expected_output_type": "EntityResearchResult",
                    "priority": 1,
                },
                {
                    "task_id": "W06_001",
                    "worker_id": "W06",
                    "objective": "依据上游研究结果生成最终报告",
                    "task_type": "write_report",
                    "args": {
                        "report_goal": "生成用户可读的实体分析报告"
                    },
                    "inputs": {
                        "upstream_results": {
                            "from_task_id": "W01_001",
                            "expected_output_type": "EntityResearchResult",
                        }
                    },
                    "constraints": ["upstream_results_only"],
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
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=FakeLLM())
    tasks, metadata = planner.plan(
        query="分析600519",
        request_mode="analysis",
        session_id="acceptance-session",
        run_id="agent_run_phase_01_3_1_acceptance",
        user_id="cht",
        focus_refs=[
            GraphRef(
                graph_id="financial_graph",
                node_id="cn:security:sse:600519",
                node_kind=GraphNodeKind.OBJECT,
                role="focus",
            )
        ],
        context_refs=[],
        memory_summary="",
        language="zh",
    )

    evidence, report_task = tasks
    checks = {
        "minimal_worker_dag": [item.worker_id for item in tasks] == ["W01", "W06"],
        "focus_ref_bound_by_code": evidence.args.get("focus_ref_ids") == [
            "cn:security:sse:600519"
        ],
        "misplaced_focus_ref_removed_from_inputs": evidence.inputs == {},
        "reply_language_bound_by_code": report_task.args.get("reply_language") == "zh",
        "semantic_dependency_compiled": report_task.dependency_task_ids == ["W01_001"],
        "main_agent_still_selected_workers": metadata.get("worker_selection_owner") == "main_agent",
        "no_post_plan_dag_mutation": metadata.get("dag_mutation_after_planning") == "forbidden",
    }
    report = {
        "phase": "01.3.1",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "planned_worker_ids": [item.worker_id for item in tasks],
        "evidence_args": evidence.args,
        "report_dependencies": report_task.dependency_task_ids,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
