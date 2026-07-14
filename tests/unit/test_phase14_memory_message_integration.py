from __future__ import annotations

import json

from agent.memory import (
    extract_memory_candidates_from_artifact,
    extract_memory_candidates_from_message_trace,
)


def test_phase14_message_trace_can_create_working_memory_candidate(tmp_path) -> None:
    messages = [
        {
            "message_id": "msg_1",
            "role": "user",
            "user_id": "u1",
            "content": "我更偏好稳健一点，记住这个偏好",
        }
    ]

    candidates = extract_memory_candidates_from_message_trace(messages, user_id="u1", output_dir=tmp_path)
    encoded = json.dumps(candidates, ensure_ascii=False)

    assert candidates
    assert "稳健" in encoded
    assert candidates[0]["memory_type"] == "WORKING"
    assert "confirmation_token" not in encoded


def test_phase14_artifact_can_create_evidence_memory_candidate_without_raw_payload(tmp_path) -> None:
    artifact = {
        "artifact_id": "artifact_1",
        "artifact_type": "tool_result",
        "user_id": "u1",
        "content_summary": {
            "message": "Evidence found for 600519.",
            "produced_outputs": ["evidence", "market_evidence"],
        },
        "produced_outputs": ["evidence", "market_evidence"],
        "metadata": {"raw_evidence": [{"chunk_id": "c1", "text": "raw"}]},
    }

    candidates = extract_memory_candidates_from_artifact(artifact, user_id="u1", output_dir=tmp_path)
    encoded = json.dumps(candidates, ensure_ascii=False)

    assert candidates
    assert candidates[0]["memory_type"] == "EVIDENCE"
    assert candidates[0]["artifact_refs"][0]["artifact_id"] == "artifact_1"
    assert "raw_evidence" not in encoded
