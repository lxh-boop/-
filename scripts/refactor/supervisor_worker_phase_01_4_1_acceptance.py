from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.planner import CoordinatorPlanner
from agent.graph.contracts import GraphNodeKind, GraphRef


class FakeRepairingLLM:
    def __init__(self) -> None:
        self.primary_error = ""
        self.repair_guidance = ""
        self.catalog: list[dict] = []

    @staticmethod
    def _invalid_candidate() -> dict:
        return {
            "tasks": [
                {
                    "task_id": "W01_001",
                    "worker_id": "W01",
                    "objective": "围绕证券600519形成实体研究结果",
                    "task_type": "analyze_entity_evidence",
                    "args": {},
                    "inputs": {
                        "focus_ref_ids": ["cn:security:sse:600519"],
                        "research_question": "分析市场背景、业务结构与行业地位",
                    },
                    "constraints": [],
                    "expected_output_type": "EntityResearchResult",
                    "priority": 1,
                },
                {
                    "task_id": "W02_001",
                    "worker_id": "W02",
                    "objective": "查询证券600519的模型预测",
                    "task_type": "query_stock_prediction",
                    "args": {},
                    "inputs": {
                        "focus_ref_ids": ["cn:security:sse:600519"],
                        "top_k": 10,
                        "model_name": "default_model",
                    },
                    "constraints": [],
                    "expected_output_type": "ModelPredictionResult",
                    "priority": 1,
                },
                {
                    "task_id": "W06_001",
                    "worker_id": "W06",
                    "objective": "汇总实体研究与模型预测",
                    "task_type": "write_report",
                    "args": {"report_goal": "分析600519"},
                    "inputs": {
                        "upstream_results": [
                            {
                                "from_task_id": "W01_001",
                                "expected_output_type": "EntityResearchResult",
                            },
                            {
                                "from_task_id": "W02_001",
                                "expected_output_type": "ModelPredictionResult",
                            },
                        ]
                    },
                    "constraints": [],
                    "expected_output_type": "FinalReport",
                    "priority": 2,
                },
            ]
        }

    @staticmethod
    def _corrected_candidate() -> dict:
        return {
            "tasks": [
                {
                    "task_id": "W01_001",
                    "worker_id": "W01",
                    "objective": "围绕证券600519形成实体研究结果",
                    "task_type": "analyze_entity_evidence",
                    "args": {
                        "research_question": "分析市场背景、业务结构与行业地位"
                    },
                    "inputs": {},
                    "constraints": [],
                    "expected_output_type": "EntityResearchResult",
                    "priority": 1,
                },
                {
                    "task_id": "W02_001",
                    "worker_id": "W02",
                    "objective": "查询证券600519的模型预测",
                    "task_type": "query_stock_prediction",
                    "args": {},
                    "inputs": {},
                    "constraints": [],
                    "expected_output_type": "ModelPredictionResult",
                    "priority": 1,
                },
                {
                    "task_id": "W06_001",
                    "worker_id": "W06",
                    "objective": "汇总实体研究与模型预测",
                    "task_type": "write_report",
                    "args": {"report_goal": "分析600519"},
                    "inputs": {
                        "upstream_results": [
                            {
                                "from_task_id": "W01_001",
                                "expected_output_type": "EntityResearchResult",
                            },
                            {
                                "from_task_id": "W02_001",
                                "expected_output_type": "ModelPredictionResult",
                            },
                        ]
                    },
                    "constraints": [],
                    "expected_output_type": "FinalReport",
                    "priority": 2,
                },
            ]
        }

    def generate_json(
        self,
        *,
        messages: list[dict],
        validator=None,
        repair_guidance: str = "",
        **_: object,
    ) -> dict:
        request = json.loads(messages[-1]["content"])
        self.catalog = request["worker_capability_catalog"]
        self.repair_guidance = repair_guidance
        invalid = self._invalid_candidate()
        try:
            if validator:
                validator(invalid)
        except Exception as exc:
            self.primary_error = str(exc)
        corrected = self._corrected_candidate()
        if validator:
            validator(corrected)
        return corrected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ref = GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        confidence=1.0,
        locked=True,
    )
    llm = FakeRepairingLLM()
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=llm)
    tasks, metadata = planner.plan(
        query="分析600519",
        request_mode="analysis",
        session_id="phase-01-4-1-session",
        run_id="agent_run_phase_01_4_1_acceptance",
        user_id="cht",
        focus_refs=[ref],
        context_refs=[],
        memory_summary="",
        language="zh",
    )
    by_id = {task.task_id: task for task in tasks}
    w02_public = next(item for item in llm.catalog if item["worker_id"] == "W02")
    prediction_contract = next(
        item
        for item in w02_public["task_contracts"]
        if item["task_type"] == "query_stock_prediction"
    )
    checks = {
        "precise_primary_error": (
            "planner_field_placement_error" in llm.primary_error
            and "move_to_args=research_question" in llm.primary_error
            and "move_to_args=model_name,top_k" in llm.primary_error
        ),
        "public_contract_renamed": (
            "input_schema" not in prediction_contract
            and "args_schema" in prediction_contract
            and "semantic_inputs_schema" in prediction_contract
        ),
        "repair_guidance_present": (
            "move_to_args" in llm.repair_guidance
            and "from_task_id" in llm.repair_guidance
        ),
        "default_top_k_is_10": by_id["W02_001"].args.get("top_k") == 10,
        "model_name_not_invented": "model_name" not in by_id["W02_001"].args,
        "w01_and_w02_parallel": (
            by_id["W01_001"].dependency_task_ids == []
            and by_id["W02_001"].dependency_task_ids == []
        ),
        "report_depends_on_both": by_id["W06_001"].dependency_task_ids
        == ["W01_001", "W02_001"],
        "main_agent_owns_dag": metadata.get("worker_selection_owner") == "main_agent",
        "no_post_plan_dag_mutation": metadata.get("dag_mutation_after_planning")
        == "forbidden",
    }
    report = {
        "phase": "01.4.1",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "primary_error": llm.primary_error,
        "planned_worker_ids": [task.worker_id for task in tasks],
        "w02_args": by_id["W02_001"].args,
    }
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
