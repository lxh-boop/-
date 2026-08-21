"""V23.0.15 compatibility marker: superseded by V23.0.16 ContextBundle tests."""
from agent.context.context_types import ContextBundle

def test_v2315_second_store_is_superseded_by_contextbundle():
    bundle=ContextBundle(user_id="u",conversation_id="s",run_id="r")
    assert bundle.metadata["working_memory_model"] == "context_bundle_per_run"
