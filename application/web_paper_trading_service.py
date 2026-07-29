from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from config import AGENT_QUANT_DB_PATH, DEFAULT_INITIAL_CASH, OUTPUT_DIR

class WebPaperTradingApplicationService:
    """Browser-facing application facade for Stage 6.3.

    The facade delegates every business decision and write to the existing paper-
    trading services, Tool Engine and WriteGateway. It does not calculate target
    weights, mutate portfolio state locally, or expose confirmation tokens.
    """

    def __init__(
        self,
        *,
        output_dir: str | Path = OUTPUT_DIR,
        db_path: str | Path | None = AGENT_QUANT_DB_PATH,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.db_path = Path(db_path) if db_path else None

    @staticmethod
    def _user_id(value: Any) -> str:
        return str(value or "refactor_test").strip() or "refactor_test"

    @staticmethod
    def _result_payload(result: Any) -> dict[str, Any]:
        if hasattr(result, "to_dict") and callable(result.to_dict):
            value = result.to_dict()
            return dict(value or {}) if isinstance(value, dict) else {"result": value}
        if isinstance(result, dict):
            return dict(result)
        return {"result": result}

    def _tool_context(self, user_id: str, *, request_id: str = "") -> dict[str, Any]:
        conversation_id = f"react-paper-trading:{user_id}"
        return {
            "user_id": user_id,
            "session_id": conversation_id,
            "conversation_id": conversation_id,
            "request_id": str(request_id or ""),
            "output_dir": self.output_dir,
            "db_path": self.db_path,
        }

    @classmethod
    def _strip_write_secrets(cls, value: Any) -> Any:
        """Remove server-only proposal material before a result reaches a presenter."""

        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for raw_key, item in value.items():
                item_key = str(raw_key)
                if item_key.lower() in {"confirmation_token", "plan_hash"}:
                    continue
                output[item_key] = cls._strip_write_secrets(item)
            return output
        if isinstance(value, (list, tuple, set)):
            return [cls._strip_write_secrets(item) for item in value]
        return value

    @staticmethod
    def _confirmation_phrase(plan_id: str) -> str:
        suffix = str(plan_id or "")[-6:].upper()
        return f"CONFIRM-{suffix}" if suffix else "CONFIRM"

    def _proposal_summary(self, plan: dict[str, Any]) -> dict[str, Any]:
        plan_id = str(plan.get("plan_id") or "")
        return {
            "plan_id": plan_id,
            "intent": str(plan.get("intent") or ""),
            "operation_type": str(plan.get("operation_type") or ""),
            "confirmation_status": str(plan.get("confirmation_status") or ""),
            "execution_status": str(plan.get("execution_status") or ""),
            "expires_at": plan.get("expires_at"),
            "created_at": plan.get("created_at"),
            "before_state_summary": plan.get("before_state_summary") or {},
            "proposed_changes": plan.get("proposed_changes") or [],
            "after_state_preview": plan.get("after_state_preview") or {},
            "warnings": plan.get("warnings") or [],
            "validation_results": plan.get("validation_results") or {},
            "confirmation_phrase": self._confirmation_phrase(plan_id),
            "token_present": bool(plan.get("confirmation_token")),
        }

    def snapshot(self, user_id: str) -> dict[str, Any]:
        user_id = self._user_id(user_id)
        from portfolio.paper_account import load_paper_cash_flows, load_paper_trading_snapshot
        from pipelines.paper_backfill_pipeline import load_paper_backfill_status
        from application.paper_profile_service import (
            get_classic_user_profile_form_options,
            has_required_paper_trading_profile,
            load_classic_user_context,
            load_current_ai_reliability_state,
            load_scheduler_status_summary,
        )

        snapshot = dict(
            load_paper_trading_snapshot(
                user_id,
                output_dir=self.output_dir,
                db_path=self.db_path,
            )
            or {}
        )
        profile = dict(
            load_classic_user_context(
                user_id,
                output_dir=self.output_dir,
                db_path=self.db_path,
            )
            or {}
        )
        return {
            **snapshot,
            "user_id": user_id,
            "profile": profile,
            "profile_complete": bool(has_required_paper_trading_profile(profile)),
            "profile_options": get_classic_user_profile_form_options(),
            "cash_flows": load_paper_cash_flows(
                user_id,
                output_dir=self.output_dir,
                db_path=self.db_path,
            )
            or [],
            "backfill_status": load_paper_backfill_status(user_id, output_dir=self.output_dir) or {},
            "ai_reliability": load_current_ai_reliability_state(user_id, output_dir=self.output_dir) or {},
            "scheduler": load_scheduler_status_summary(self.output_dir) or {},
        }

    def profile(self, user_id: str) -> dict[str, Any]:
        from application.paper_profile_service import (
            get_classic_user_profile_form_options,
            has_required_paper_trading_profile,
            load_classic_user_context,
        )

        user_id = self._user_id(user_id)
        profile = dict(
            load_classic_user_context(
                user_id,
                output_dir=self.output_dir,
                db_path=self.db_path,
            )
            or {}
        )
        return {
            "user_id": user_id,
            "profile": profile,
            "complete": bool(has_required_paper_trading_profile(profile)),
            "options": get_classic_user_profile_form_options(),
        }

    def save_profile(
        self,
        *,
        user_id: str,
        profile: dict[str, Any],
        request_id: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("profile_update_confirmation_required")
        if not str(request_id or "").strip():
            raise ValueError("request_id_required")
        if not str(idempotency_key or "").strip():
            raise ValueError("idempotency_key_required")
        user_id = self._user_id(user_id)
        payload = dict(profile or {})
        payload["user_id"] = user_id
        from application.paper_profile_service import save_classic_user_context

        result = save_classic_user_context(
            payload,
            output_dir=self.output_dir,
            db_path=self.db_path,
        )
        return {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "status": str((result or {}).get("status") or "saved"),
            "profile": self.profile(user_id)["profile"],
        }

    def proposals(self, user_id: str) -> list[dict[str, Any]]:
        user_id = self._user_id(user_id)
        from agent.session.pending_action_store import load_pending_actions

        actions = load_pending_actions(user_id, self.output_dir)
        allowed_intents = {"capital_change", "paper_backfill"}
        records = [
            self._proposal_summary(dict(plan or {}))
            for plan in actions.values()
            if str((plan or {}).get("intent") or "") in allowed_intents
        ]
        return sorted(records, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def preview_capital_change(
        self,
        *,
        user_id: str,
        flow_type: str,
        amount: float,
        effective_date: str | None,
        reason: str,
        request_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not str(request_id or "").strip() or not str(idempotency_key or "").strip():
            raise ValueError("request_id_and_idempotency_key_required")
        user_id = self._user_id(user_id)
        normalized_type = str(flow_type or "").strip().lower()
        if normalized_type not in {"deposit", "withdrawal"}:
            raise ValueError("invalid_flow_type")
        if float(amount or 0) <= 0:
            raise ValueError("amount_must_be_positive")
        from agent.session.pending_action_store import get_pending_plan
        from agent.tool_engine import AGENT_MAIN, execute_tool

        result = execute_tool(
            "capital.change.preview",
            {
                "user_id": user_id,
                "flow_type": normalized_type,
                "amount": float(amount),
                "effective_date": str(effective_date or date.today().isoformat()),
                "reason": str(reason or ""),
                "idempotency_key": str(idempotency_key),
            },
            context=self._tool_context(user_id, request_id=request_id),
            agent_type=AGENT_MAIN,
        )
        payload = self._result_payload(result)
        plan_id = str((payload.get("data") or {}).get("plan_id") or "")
        plan = get_pending_plan(user_id, plan_id, self.output_dir) if plan_id else None
        return {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "result": self._strip_write_secrets(payload),
            "proposal": self._proposal_summary(plan) if plan else None,
        }

    def preview_backfill(
        self,
        *,
        user_id: str,
        start_date: str,
        end_date: str,
        initial_cash: float | None,
        force: bool,
        resume: bool,
        request_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not str(request_id or "").strip() or not str(idempotency_key or "").strip():
            raise ValueError("request_id_and_idempotency_key_required")
        if not str(start_date or "").strip():
            raise ValueError("start_date_required")
        user_id = self._user_id(user_id)
        profile = self.profile(user_id)["profile"]
        capital = float(initial_cash or profile.get("available_capital") or DEFAULT_INITIAL_CASH)
        from agent.session.pending_action_store import get_pending_plan
        from agent.tool_engine import AGENT_MAIN, execute_tool

        result = execute_tool(
            "backfill.preview",
            {
                "user_id": user_id,
                "start_date": str(start_date),
                "end_date": str(end_date or "latest"),
                "initial_cash": capital,
                "resume": bool(resume),
                "force": bool(force),
                "skip_news": False,
                "strategy": "top10_buffer",
                "top_k": 10,
                "entry_top_k": 10,
                "hold_buffer_rank": 15,
                "max_positions": 10,
                "continue_on_error": True,
                "idempotency_key": str(idempotency_key),
            },
            context=self._tool_context(user_id, request_id=request_id),
            agent_type=AGENT_MAIN,
        )
        payload = self._result_payload(result)
        plan_id = str((payload.get("data") or {}).get("plan_id") or "")
        plan = get_pending_plan(user_id, plan_id, self.output_dir) if plan_id else None
        return {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "result": self._strip_write_secrets(payload),
            "proposal": self._proposal_summary(plan) if plan else None,
        }

    def commit_proposal(
        self,
        *,
        user_id: str,
        plan_id: str,
        confirmation_text: str,
        request_id: str,
        idempotency_key: str,
        allow_long_running: bool = False,
    ) -> dict[str, Any]:
        if not str(request_id or "").strip() or not str(idempotency_key or "").strip():
            raise ValueError("request_id_and_idempotency_key_required")
        user_id = self._user_id(user_id)
        from agent.session.pending_action_store import get_pending_plan

        plan = get_pending_plan(user_id, str(plan_id), self.output_dir)
        if not plan:
            raise ValueError("proposal_not_found")
        if str(plan.get("intent") or "") == "paper_backfill" and not allow_long_running:
            raise ValueError("paper_backfill_requires_task_runtime")
        expected = self._confirmation_phrase(str(plan_id))
        if str(confirmation_text or "").strip().upper() != expected:
            raise ValueError("confirmation_text_mismatch")
        token = str(plan.get("confirmation_token") or "")
        if not token:
            raise ValueError("confirmation_token_missing_on_server")
        from agent.write_gateway import execute_confirmed_plan_v2

        result = execute_confirmed_plan_v2(
            plan_id=str(plan_id),
            confirmation_token=token,
            user_id=user_id,
            conversation_id=f"react-paper-trading:{user_id}",
            output_dir=self.output_dir,
            db_path=self.db_path,
        )
        return {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "result": self._strip_write_secrets(self._result_payload(result)),
            "proposal": self._proposal_summary(
                get_pending_plan(user_id, str(plan_id), self.output_dir) or plan
            ),
        }

    def reject_proposal(
        self,
        *,
        user_id: str,
        plan_id: str,
        reason: str,
        request_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not str(request_id or "").strip() or not str(idempotency_key or "").strip():
            raise ValueError("request_id_and_idempotency_key_required")
        user_id = self._user_id(user_id)
        from agent.session.confirmation_manager import reject_confirmation_plan

        success, status, plan = reject_confirmation_plan(
            user_id,
            str(plan_id),
            output_dir=self.output_dir,
            db_path=self.db_path,
            reason=str(reason or "user_rejected"),
        )
        return {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "success": bool(success),
            "status": status,
            "proposal": self._proposal_summary(plan) if plan else None,
        }

    def cancel_cash_flow(
        self,
        *,
        user_id: str,
        cash_flow_id: str,
        request_id: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("cash_flow_cancel_confirmation_required")
        if not str(request_id or "").strip() or not str(idempotency_key or "").strip():
            raise ValueError("request_id_and_idempotency_key_required")
        user_id = self._user_id(user_id)
        from portfolio.paper_account import cancel_pending_paper_cash_flow

        result = cancel_pending_paper_cash_flow(
            str(cash_flow_id),
            user_id,
            output_dir=self.output_dir,
            db_path=self.db_path,
        )
        return {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "result": result,
        }


web_paper_trading_service = WebPaperTradingApplicationService()
