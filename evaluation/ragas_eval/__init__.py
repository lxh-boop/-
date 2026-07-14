"""Offline RAG/Ragas evaluation utilities.

This package is intentionally isolated from the production RAG, Agent, daily
update, and Streamlit paths. Optional Ragas imports must stay inside this
package and be lazy.
"""

from evaluation.ragas_eval.schemas import EvaluationCase, RetrievedContext

__all__ = ["EvaluationCase", "RetrievedContext"]
