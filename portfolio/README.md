# Portfolio / Paper Trading Foundation

`portfolio/` is the Stage 2C paper-trading foundation. It provides user-profile constraints, simulated accounts, simulated positions, simulated orders, portfolio risk checks, first-version rebalance rules, a paper execution engine, and database-first storage.

This module never connects to a real broker and never executes real trades. All account, order, and rebalance outputs are paper trading records for machine-learning research, quantitative strategy validation, and project demonstration only. They do not constitute investment advice.

## Core Flow

1. `user_profile.py` loads the user profile, risk assessment, and investment goal from `database/`, or creates a default balanced profile when user data is missing.
2. `portfolio_risk.py` checks whether the current simulated portfolio matches the user constraints.
3. `rebalance_rules.py` converts final candidate stocks into a `RebalancePlan` with target action, target weight, reason, and risk warning.
4. `paper_trading_engine.py` converts the plan into simulated paper orders and updates simulated cash and positions.
5. `storage.py` writes to the database first. If the database is unavailable, it falls back to `outputs/portfolio/`.

## Fallback Files

When database storage is unavailable, records are written under:

- `outputs/portfolio/paper_account.json`
- `outputs/portfolio/paper_positions.csv`
- `outputs/portfolio/paper_orders.csv`
- `outputs/portfolio/portfolio_risk_report.json`

Stage 3 Signal Fusion can consume this module after model prediction, news/RAG evidence, and agent constraints have produced final candidate actions.
