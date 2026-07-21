from __future__ import annotations

import hashlib
from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_generated_code_cannot_write_formal_project(tmp_path) -> None:
    formal = Path("portfolio/hierarchical_top10_allocator.py")
    before = hashlib.sha256(formal.read_bytes()).hexdigest()

    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "code",
            "new_capability_spec": {
                "name": "dynamic_exposure",
                "requested_output_path": str(formal),
            },
        },
    )

    after = hashlib.sha256(formal.read_bytes()).hexdigest()
    root = Path(result.data["artifact_root"])
    assert result.success
    assert before == after
    assert all(
        path.resolve().is_relative_to(root.resolve())
        for path in root.rglob("*")
    )
