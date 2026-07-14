# AI Adjustment Evaluation

`evaluation/` records whether AI/news/user/risk post-processing improved the original K-line model decision.

The first version uses local fallback files:

```text
outputs/evaluation/ai_adjustment_evaluation.csv
outputs/evaluation/ai_reliability_state.json
```

Core ideas:

```text
ordinary risk -> reduce target weight
hard risk -> exclude
future returns missing -> pending
good historical adjustment -> higher ai_reliability_weight
bad historical adjustment -> lower ai_reliability_weight
```

`ai_reliability_weight` is user-specific and starts at `0.00` during cold start. If a user has fewer than 20 evaluated samples, status remains `cold_start` and reliability stays `0.00`. After enough evaluated samples are available, the weight is clamped to `0.00 ~ 1.00` and changes only the strength of non-hard-risk AI reductions. Hard risks such as ST, delisting risk, serious violations, extremely poor liquidity, or high-confidence major negative news can still force `exclude`.

All outputs are for machine-learning research, paper-trading validation, and project demonstration only. They are not investment advice and do not connect to real trading.
