from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.agent_protocol import AgentOutput, make_message_id, output_summary
from agent.agent_specs import RISK_OPERATION, get_agent_spec, validate_tool_allowed
from agent.tool_engine import AGENT_MAIN, execute_tool
from agent.tools._common import normalize_stock_code, safe_float


def _portfolio_state_from_output(portfolio_output: dict[str, Any] | None) -> dict[str, Any]:
    for result in ((portfolio_output or {}).get("analysis") or {}).get("task_result_summary") or []:
        if isinstance(result, dict) and result.get("intent") == "portfolio_state":
            return dict(result.get("data") or {})
    return {}


def _find_position(portfolio_state: dict[str, Any], stock_code: str) -> dict[str, Any]:
    code = normalize_stock_code(stock_code)
    for row in portfolio_state.get("positions") or []:
        if not isinstance(row, dict):
            continue
        if normalize_stock_code(row.get("stock_code")) == code and safe_float(row.get("quantity"), 0.0) > 0:
            return row
    return {}


def _precheck_summary(
    *,
    stock_code: str,
    portfolio_state: dict[str, Any],
    preview_data: dict[str, Any],
) -> dict[str, Any]:
    position = _find_position(portfolio_state, stock_code)
    estimated_quantity = safe_float(
        preview_data.get("estimated_quantity") or preview_data.get("estimated_trade_quantity"),
        0.0,
    )
    target_weight = safe_float(
        preview_data.get("target_weight") or preview_data.get("recommended_weight"),
        0.0,
    )
    return {
        "stock_code": normalize_stock_code(stock_code),
        "account_present": bool(portfolio_state.get("account") or preview_data.get("before")),
        "cash": portfolio_state.get("cash"),
        "total_assets": portfolio_state.get("total_assets"),
        "position_count": portfolio_state.get("position_count"),
        "holding_present": bool(position),
        "current_quantity": position.get("quantity") if position else preview_data.get("current_quantity"),
        "estimated_quantity": estimated_quantity,
        "a_share_lot_valid": estimated_quantity > 0 and estimated_quantity % 100 == 0,
        "target_weight": target_weight,
        "single_position_cap_observed": target_weight <= 0.30 + 1e-9 if target_weight else True,
        "requires_confirmation": bool(preview_data.get("plan_id")),
    }


class RiskOperationAgent:
    role = RISK_OPERATION

    def __init__(self) -> None:
        self.spec = get_agent_spec(self.role)

    def run(
        self,
        *,
        query: str,
        operation_params: dict[str, Any],
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        session_id: str,
        portfolio_output: dict[str, Any] | None = None,
        market_output: dict[str, Any] | None = None,
        handoff_from: str = "portfolio_analysis",
        handoff_to: str = "user_confirmation",
    ) -> tuple[AgentOutput, dict[str, Any], dict[str, Any]]:
        validate_tool_allowed(self.role, "manual_position_operation_tool")
        stock_code = normalize_stock_code(operation_params.get("stock_code"))
        result = execute_tool(
            "portfolio.preview_manual_change",
            {
                "user_id": user_id,
                "stock_code": stock_code,
                "requested_weight": operation_params.get("requested_weight"),
                "position_adjustment_ratio": operation_params.get("position_adjustment_ratio"),
                "requested_quantity": operation_params.get("requested_quantity"),
                "cash_weight": operation_params.get("cash_weight"),
                "target_position_count": operation_params.get("target_position_count"),
                "query": str(operation_params.get("query") or query),
                "top_k": default_top_k,
            },
            context={
                "user_id": user_id,
                "output_dir": output_dir,
                "db_path": db_path,
                "session_id": session_id,
                "conversation_id": session_id,
                "query": query,
            },
            agent_type=AGENT_MAIN,
        )
        result_dict = result.to_legacy_dict() if hasattr(result, "to_legacy_dict") else dict(result)
        data = dict(result_dict.get("data") or {})
        result_dict = {
            **dict(result_dict),
            "data": data,
            "requires_confirmation": bool(result_dict.get("requires_confirmation") or data.get("plan_id")),
        }
        if data.get("plan_id"):
            result_dict["plan_id"] = data.get("plan_id")
        portfolio_state = _portfolio_state_from_output(portfolio_output)
        prechecks = _precheck_summary(
            stock_code=stock_code,
            portfolio_state=portfolio_state,
            preview_data=data,
        )
        message_id = make_message_id(self.role)
        output = AgentOutput(
            role=self.role,
            message_id=message_id,
            status="succeeded" if result_dict.get("success") else "failed",
            evidence=[],
            analysis={
                "prechecks": prechecks,
                "market_handoff_status": (market_output or {}).get("status", ""),
                "portfolio_handoff_status": (portfolio_output or {}).get("status", ""),
            },
            proposal={
                "plan_id": data.get("plan_id", ""),
                "operation_type": data.get("operation_type", "one_time_position_operation"),
                "requires_confirmation": bool(result_dict.get("requires_confirmation") or data.get("plan_id")),
                "execution_allowed_without_confirmation": False,
                "estimated_quantity": data.get("estimated_quantity"),
                "target_weight": data.get("target_weight") or data.get("recommended_weight"),
            },
            risks=list(result_dict.get("errors") or []),
            next_actions=[
                "wait_for_user_confirmation" if data.get("plan_id") else "regenerate_operation_request",
            ],
            sources=[],
            tool_calls=[
                {
                    "task_id": "task_risk_operation_preview",
                    "tool_name": "portfolio.preview_manual_change",
                    "success": bool(result_dict.get("success")),
                    "arguments": {
                        "stock_code": stock_code,
                        "requested_weight": operation_params.get("requested_weight"),
                        "position_adjustment_ratio": operation_params.get("position_adjustment_ratio"),
                        "requested_quantity": operation_params.get("requested_quantity"),
                    },
                    "step_status": "succeeded" if result_dict.get("success") else "failed",
                    "agent_role": self.role,
                }
            ],
            handoff_from=handoff_from,
            handoff_to=handoff_to,
        )
        task_result = {
            "task_id": "task_risk_operation_preview",
            "intent": "portfolio.preview_manual_change",
            "success": bool(result_dict.get("success")),
            "step_status": "succeeded" if result_dict.get("success") else "failed",
            "execution_mode": "agent_preview",
            "arguments": {
                "stock_code": stock_code,
                "requested_weight": operation_params.get("requested_weight"),
                "position_adjustment_ratio": operation_params.get("position_adjustment_ratio"),
                "requested_quantity": operation_params.get("requested_quantity"),
            },
            "message": str(result_dict.get("message") or ""),
            "data": data,
            "warnings": list(result_dict.get("warnings") or []),
            "errors": list(result_dict.get("errors") or []),
        }
        orchestration = {
            "success": bool(result_dict.get("success")),
            "answer": "",
            "task_results": {"task_risk_operation_preview": task_result},
            "tool_calls": output.tool_calls,
            "execution_batches": [["task_risk_operation_preview"]],
            "warnings": list(result_dict.get("warnings") or []),
            "errors": list(result_dict.get("errors") or []),
            "execution_status": "waiting_for_approval" if data.get("plan_id") else "failed",
            "agent_output_summary": output_summary(output),
        }
        return output, orchestration, result_dict
