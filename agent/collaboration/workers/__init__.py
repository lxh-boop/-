"""Domain-scoped Worker executors used by the collaboration runtime.

Each module accepts an already assigned ``GraphAgentTask`` and returns one
``GraphWorkerResult``. Cross-Worker planning and DAG ownership remain with the
main coordinator.
"""

from .diagnostic import compose_diagnostic_result
from .evidence import compose_evidence_result, provided_evidence_result
from .graph_impact import compose_graph_impact_result
from .portfolio import compose_portfolio_result
from .report_writer import run_report_writer
from .risk import compose_risk_result
from .strategy_guard import compose_strategy_guard_result

__all__ = [
    "compose_diagnostic_result",
    "compose_evidence_result",
    "compose_graph_impact_result",
    "compose_portfolio_result",
    "compose_risk_result",
    "compose_strategy_guard_result",
    "provided_evidence_result",
    "run_report_writer",
]
