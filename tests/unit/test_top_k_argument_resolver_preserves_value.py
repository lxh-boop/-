from agent.orchestration.argument_resolver import resolve_task_arguments


def test_top_k_argument_resolver_preserves_value() -> None:
    resolved = resolve_task_arguments(
        {"intent": "ranking", "parameters": {"top_k": 50}},
        task_results={},
        context={"user_explicit_top_k": 10, "default_top_k": 20},
        default_top_k=20,
    )

    assert resolved["top_k"] == 10
