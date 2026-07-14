from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from portfolio.schemas import now_text


@dataclass
class ConversationState:
    session_id: str = field(default_factory=lambda: f"agent_session_{uuid4().hex[:10]}")
    user_id: str = "default"
    selected_stock_code: str = ""
    current_intent: str = ""
    pending_plan_id: str = ""
    pending_confirmation_token: str = ""
    last_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=now_text)
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def session_dir(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "agent_sessions" / str(user_id)
