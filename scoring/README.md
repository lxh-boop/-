# Signal Fusion Foundation

`scoring/` combines model prediction, news/RAG evidence, user suitability, portfolio context, and Agent-side evidence into numeric position adjustments. It is not an Agent, does not predict stock direction again, does not call an LLM, does not produce real trading instructions, and does not promise returns.

Stage 35 removes action labels and penalty fields from new outputs. `FusionOutput` should expose numeric adjustment fields only:

```text
effective_news_adjustment = ai_reliability_weight * news_adjustment
combined_adjustment = effective_news_adjustment + user_adjustment
position_adjustment_ratio = clip(1 + combined_adjustment, 0.0, 2.0)
```

`ai_reliability_weight` scales news adjustment only. User suitability remains a deterministic `user_adjustment`. Portfolio and paper trading handle execution constraints such as 80% total target, 30% single-stock cap, one-lot quantity, valid price, cash, fees, and tradability.

## Flow

```text
ModelPredictionSignal
    + NewsEvidenceSignal / RAG evidence
    + UserConstraintSignal
    + PortfolioConstraintSignal
    + Agent evidence
    -> fuse_signal()
    -> FusionOutput
    -> decision_logger.log_fusion_output()
```

Every `FusionOutput` can retain evidence IDs, evidence snapshots, reasons, risk notes, and compliance disclaimer for audit. It must not write action labels or risk/rule penalty fields in new CSV, JSON, database, UI, or audit outputs.
