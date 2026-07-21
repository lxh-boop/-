from agent.intent_decomposition.rule_fallback import decompose_with_rules
from agent.orchestration.argument_resolver import resolve_task_arguments


def test_top_k_rule_fallback_preserves_request_default() -> None:
    result = decompose_with_rules("推荐一个比现在更稳健的持仓，并说明为什么稳健")
    ranking = next(task.to_dict() for task in result.tasks if task.intent == "ranking")
    resolved = resolve_task_arguments(ranking, task_results={}, context={"default_top_k": 10}, default_top_k=10)

    assert resolved["top_k"] == 10
