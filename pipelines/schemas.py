from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PipelineStatus:
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL = "partial"


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _path_text(value: str | Path | None) -> str:
    return str(value or "")


@dataclass(frozen=True)
class PipelineContext:
    user_id: str = "default"
    trade_date: str = "latest"
    decision_time: str = ""
    stock_pool: str = "csi300"
    model_name: str = "chronos_bolt_small"
    model_version: str = "latest"
    top_k: int = 50
    output_dir: str | Path = "outputs"
    db_path: str | Path | None = None
    dry_run: bool = False
    paper_trading_enabled: bool = True
    strategy: str = "hierarchical_top10"
    entry_top_k: int = 10
    hold_buffer_rank: int = 15
    max_positions: int = 10
    minimum_cash_ratio: float = 0.05
    min_rebalance_weight_delta: float = 0.01
    execution_price_type: str = "close"
    job_id: str = ""
    run_id: str = ""
    execution_source: str = ""

    def resolved_output_dir(self) -> Path:
        return Path(self.output_dir)

    def with_trade_date(self, trade_date: str) -> "PipelineContext":
        return PipelineContext(
            user_id=self.user_id,
            trade_date=trade_date,
            decision_time=self.decision_time,
            stock_pool=self.stock_pool,
            model_name=self.model_name,
            model_version=self.model_version,
            top_k=self.top_k,
            output_dir=self.output_dir,
            db_path=self.db_path,
            dry_run=self.dry_run,
            paper_trading_enabled=self.paper_trading_enabled,
            strategy=self.strategy,
            entry_top_k=self.entry_top_k,
            hold_buffer_rank=self.hold_buffer_rank,
            max_positions=self.max_positions,
            minimum_cash_ratio=self.minimum_cash_ratio,
            min_rebalance_weight_delta=self.min_rebalance_weight_delta,
            execution_price_type=self.execution_price_type,
            job_id=self.job_id,
            run_id=self.run_id,
            execution_source=self.execution_source,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["output_dir"] = _path_text(self.output_dir)
        data["db_path"] = _path_text(self.db_path)
        return data


@dataclass(frozen=True)
class BasePipelineResult:
    status: str = PipelineStatus.SUCCESS
    message: str = ""
    input_count: int = 0
    output_count: int = 0
    output_paths: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_text)

    @property
    def ok(self) -> bool:
        return self.status == PipelineStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PredictionPipelineResult(BasePipelineResult):
    predictions: list[Any] = field(default_factory=list)
    source: str = ""


@dataclass(frozen=True)
class RAGPipelineResult(BasePipelineResult):
    evidence: list[Any] = field(default_factory=list)
    retrieval_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SignalFusionPipelineResult(BasePipelineResult):
    recommendations: list[Any] = field(default_factory=list)
    fusion_outputs: list[Any] = field(default_factory=list)
    decision_log_count: int = 0


@dataclass(frozen=True)
class PaperTradingPipelineResult(BasePipelineResult):
    plan: Any | None = None
    account: Any | None = None
    positions: list[Any] = field(default_factory=list)
    orders: list[Any] = field(default_factory=list)
    is_paper_trading: bool = True


@dataclass(frozen=True)
class ReportPipelineResult(BasePipelineResult):
    report_path: str = ""
    report_text: str = ""


@dataclass(frozen=True)
class DailyUpdatePipelineResult(BasePipelineResult):
    step_results: dict[str, BasePipelineResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["step_results"] = {name: result.to_dict() for name, result in self.step_results.items()}
        return data
