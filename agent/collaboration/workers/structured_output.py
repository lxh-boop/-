"""Worker-local structured-output generation with one minimal repair pass.

The repair pass is deliberately isolated from the original business context.
It receives only the invalid output, the validation error, the target schema,
and caller-approved immutable references.  This keeps schema repair from
becoming a second business-reasoning pass.
"""

from __future__ import annotations

from typing import Any, Callable

from core.llm import LLMService
from core.llm.contracts import LLMJSONError, extract_json_object
from core.llm.prompt_compaction import compact_json_dumps, schema_for_prompt


Validator = Callable[[dict[str, Any]], None]


def _generate_text_no_thinking(
    llm_service: LLMService,
    *,
    stage: str,
    messages: list[dict[str, Any]],
    max_output_tokens: int,
    operation: str,
    disable_thinking: bool,
) -> str:
    return str(llm_service.generate_text(
        stage=stage,
        messages=messages,
        max_output_tokens=max_output_tokens,
        temperature=0.0,
        operation=operation,
        disable_thinking=bool(disable_thinking),
    ) or "")


def generate_json_with_local_structural_repair(
    llm_service: LLMService,
    *,
    stage: str,
    operation: str,
    messages: list[dict[str, Any]],
    output_schema: dict[str, Any],
    validator: Validator,
    immutable_repair_context: dict[str, Any] | None = None,
    repair_guidance: str = "",
    primary_max_output_tokens: int = 3200,
    repair_max_output_tokens: int = 2200,
    max_invalid_output_chars: int = 12000,
    primary_disable_thinking: bool = False,
) -> dict[str, Any]:
    """Generate one business JSON object and permit one structural repair only.

    The repair request never receives the original business prompt/messages.
    ``immutable_repair_context`` may contain only identifiers or other values
    that the repair function is allowed to preserve/validate; it must not be a
    copy of the business evidence/context.
    """

    primary_text = _generate_text_no_thinking(
        llm_service,
        stage=stage,
        messages=messages,
        max_output_tokens=primary_max_output_tokens,
        operation=operation,
        disable_thinking=primary_disable_thinking,
    )
    try:
        primary = extract_json_object(primary_text)
        validator(primary)
        return primary
    except Exception as primary_exc:
        repair_request = {
            "task": "repair_existing_json_only",
            "instruction": (
                "Repair only JSON syntax/shape and validator-reported contract fields. "
                "Do not redo business reasoning, do not add facts, and do not infer missing business content. "
                "Preserve valid values from invalid_output. If truncated content cannot be recovered from "
                "invalid_output, use the smallest schema-valid empty/default value instead of inventing content."
            ),
            "repair_guidance": str(repair_guidance or "")[:4000],
            "validation_error": {
                "type": type(primary_exc).__name__,
                "message": str(primary_exc)[:2000],
            },
            "immutable_context": dict(immutable_repair_context or {}),
            "output_schema": schema_for_prompt(output_schema),
            "invalid_output": primary_text[:max_invalid_output_chars],
        }
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "You are a JSON structural repair function. Never perform business reasoning. "
                    "Use only invalid_output and immutable_context. Return exactly one complete JSON object."
                ),
            },
            {"role": "user", "content": compact_json_dumps(repair_request)},
        ]
        repaired_text = _generate_text_no_thinking(
            llm_service,
            stage=stage,
            messages=repair_messages,
            max_output_tokens=repair_max_output_tokens,
            operation="schema_repair_structural_only",
            disable_thinking=True,
        )
        try:
            repaired = extract_json_object(repaired_text)
            validator(repaired)
            return repaired
        except Exception as repair_exc:
            raise LLMJSONError(
                "Worker local structured-output recovery exhausted: "
                f"primary={type(primary_exc).__name__}:{str(primary_exc)[:800]}; "
                f"repair={type(repair_exc).__name__}:{str(repair_exc)[:800]}"
            ) from repair_exc


__all__ = ["generate_json_with_local_structural_repair"]
