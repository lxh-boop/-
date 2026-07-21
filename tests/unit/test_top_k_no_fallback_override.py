from agent.intent_decomposition.rule_fallback import decompose_with_rules


def test_top_k_no_fallback_override() -> None:
    result = decompose_with_rules("推荐一个比现在更稳健的持仓，并说明为什么稳健")
    ranking = next(task for task in result.tasks if task.intent == "ranking")

    assert "top_k" not in ranking.parameters
