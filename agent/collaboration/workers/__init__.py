"""Domain-scoped Worker executors used by the collaboration runtime.

Each module accepts an already assigned ``GraphAgentTask`` and returns one
``GraphWorkerResult``. Cross-Worker planning and DAG ownership remain with the
main coordinator.
"""

from .diagnostic import run_diagnostic
from .entity_analysis import run_entity_analysis
from .evidence import run_evidence
from .graph_context import run_graph_context
from .graph_impact import run_graph_impact
from .internal_system import run_internal_system
from .report_writer import run_report_writer
from .risk import run_risk
from .strategy_guard import run_strategy_guard

__all__ = [
    "run_diagnostic",
    "run_evidence",
    "run_entity_analysis",
    "run_graph_context",
    "run_graph_impact",
    "run_internal_system",
    "run_report_writer",
    "run_risk",
    "run_strategy_guard",
]
