from __future__ import annotations

from agent.orchestration.multi_task_executor import execute_multi_intent_plan
from agent.sandbox import run_python_analysis, validate_python_analysis_code
from agent.tools.tool_registry import get_tool_registry


def test_python_sandbox_runs_read_only_analysis() -> None:
    result = run_python_analysis(
        "import statistics\nvalues = SNAPSHOT['values']\nRESULT = {'mean': statistics.mean(values)}",
        snapshot={"values": [1, 2, 3]},
        snapshot_id="snap_1",
    )

    assert result["success"] is True
    assert result["status"] == "succeeded"
    assert result["result"] == {"mean": 2}
    assert result["snapshot_id"] == "snap_1"


def test_python_sandbox_rejects_dangerous_code() -> None:
    assert "blocked_import:os" in validate_python_analysis_code("import os\nRESULT = 1")
    assert "blocked_call:open" in validate_python_analysis_code("RESULT = open('x.txt').read()")
    assert "blocked_call:read_csv" in validate_python_analysis_code("RESULT = pd.read_csv('D:/secret.csv')")

    result = run_python_analysis("import os\nRESULT = os.environ", snapshot={})
    assert result["success"] is False
    assert result["status"] == "rejected"
    assert result["error_type"] == "sandbox_security_rejected"


def test_python_sandbox_timeout_and_output_limit() -> None:
    timeout = run_python_analysis("while True:\n    pass", snapshot={}, timeout_seconds=0.5)
    assert timeout["success"] is False
    assert timeout["status"] == "timeout"
    assert timeout["error_type"] == "sandbox_timeout"

    noisy = run_python_analysis(
        "print('x' * 2000)\nRESULT = {'ok': True}",
        snapshot={},
        max_output_chars=200,
    )
    assert noisy["success"] is True
    assert noisy["result"] == {"ok": True}
    assert "stdout_truncated" in noisy["warnings"]
    assert len(noisy["stdout_summary"]) <= 230


def test_python_sandbox_is_registered_as_read_only_analysis_tool(tmp_path) -> None:
    spec = get_tool_registry()["python_sandbox_analysis"]
    assert spec.read_only is True
    assert spec.has_side_effect is False
    assert spec.requires_confirmation is False
    assert spec.concurrency_safe is True

    result = execute_multi_intent_plan(
        {
            "tasks": [
                {
                    "task_id": "task_1",
                    "intent": "python_sandbox_analysis",
                    "parameters": {
                        "code": "RESULT = {'total': sum(SNAPSHOT['values'])}",
                        "snapshot": {"values": [2, 3, 5]},
                    },
                    "depends_on": [],
                }
            ]
        },
        user_id="u1",
        output_dir=tmp_path,
    )

    assert result["success"] is True
    assert result["task_results"]["task_1"]["data"]["result"] == {"total": 10}
