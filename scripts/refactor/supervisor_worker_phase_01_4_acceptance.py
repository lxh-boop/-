from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.collaboration.agent_directory import AgentDirectory, W02
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.graph.contracts import GraphNodeKind, GraphRef


class FakeLLM:
    def generate_json(self, *, validator=None, **_: object) -> dict:
        payload = {
            "tasks": [
                {
                    "task_id": "W01_001", "worker_id": "W01",
                    "objective": "研究该金融实体的外部证据",
                    "task_type": "retrieve_evidence",
                    "args": {"research_question": "分析公司与市场证据"},
                    "inputs": {}, "constraints": [],
                    "expected_output_type": "EntityResearchResult", "priority": 1,
                },
                {
                    "task_id": "W02_001", "worker_id": "W02",
                    "objective": "查询该证券的内部模型预测",
                    "task_type": "query_stock_prediction",
                    "args": {"top_k": 10}, "inputs": {}, "constraints": [],
                    "expected_output_type": "ModelPredictionResult", "priority": 1,
                },
                {
                    "task_id": "W06_001", "worker_id": "W06",
                    "objective": "汇总外部证据与内部模型预测",
                    "task_type": "write_report",
                    "args": {"report_goal": "分析600519"},
                    "inputs": {"upstream_results": [
                        {"from_task_id": "W01_001", "expected_output_type": "EntityResearchResult"},
                        {"from_task_id": "W02_001", "expected_output_type": "ModelPredictionResult"},
                    ]},
                    "constraints": [], "expected_output_type": "FinalReport", "priority": 2,
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
    ref = GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        confidence=1.0,
        locked=True,
    )
    directory = AgentDirectory()
    planner = CoordinatorPlanner(directory, llm_service=FakeLLM())
    tasks, metadata = planner.plan(
        query="分析600519", request_mode="analysis",
        session_id="phase-01-4-session", run_id="agent_run_phase_01_4_acceptance",
        user_id="cht", focus_refs=[ref], context_refs=[], memory_summary="", language="zh",
    )
    by_id = {task.task_id: task for task in tasks}
    with tempfile.TemporaryDirectory() as temp:
        output_dir = Path(temp)
        pd.DataFrame([{
            "rank": 1, "date": "2026-07-28", "code": "600519", "name": "贵州茅台",
            "pred_5d_ret": 0.023, "up_prob": 0.64, "score": 0.71,
            "confidence": 0.76, "risk_level": "medium", "model_name": "StockRouter",
        }]).to_csv(output_dir / "ranking_latest.csv", index=False, encoding="utf-8-sig")
        runtime = SpecialistRuntime(
            llm_service=SimpleNamespace(), provider=SimpleNamespace(), impact_service=SimpleNamespace()
        )
        prediction = runtime.run(
            by_id["W02_001"], current_user_request="分析600519", dependency_results={},
            output_dir=output_dir, db_path=None, default_top_k=10, language="zh",
        )
    original_report_dependencies = list(by_id["W06_001"].dependency_task_ids)
    dependencies = {"W02_001": prediction.safe_for_coordinator()}
    report_probe = by_id["W06_001"]
    report_probe.inputs = {
        "upstream_results": [
            {"from_task_id": "W02_001", "expected_output_type": "ModelPredictionResult"}
        ]
    }
    report_probe.dependency_task_ids = ["W02_001"]
    resolved = directory.resolve_task_inputs(report_probe, dependencies)
    checks = {
        "planned_worker_ids": [task.worker_id for task in tasks] == ["W01", "W02", "W06"],
        "w01_and_w02_parallel": by_id["W01_001"].dependency_task_ids == [] and by_id["W02_001"].dependency_task_ids == [],
        "report_depends_on_both": original_report_dependencies == ["W01_001", "W02_001"],
        "focus_ref_bound_to_w02": by_id["W02_001"].args.get("focus_ref_ids") == [ref.node_id],
        "typed_prediction_payload": prediction.output_type == "ModelPredictionResult" and prediction.payload.get("rank") == 1,
        "explicit_input_binding": resolved["upstream_results"][0]["payload"].get("record", {}).get("score") == 0.71,
        "main_agent_owns_dag": metadata.get("worker_selection_owner") == "main_agent",
        "no_post_plan_dag_mutation": metadata.get("dag_mutation_after_planning") == "forbidden",
    }
    report = {
        "phase": "01.4",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "planned_worker_ids": [task.worker_id for task in tasks],
        "prediction_payload": prediction.payload,
    }
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
