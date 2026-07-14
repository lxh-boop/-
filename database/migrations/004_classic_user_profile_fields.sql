ALTER TABLE user_profile ADD COLUMN nickname TEXT;
ALTER TABLE user_profile ADD COLUMN income_stability TEXT;

ALTER TABLE trading_behavior ADD COLUMN avoided_industries TEXT;
ALTER TABLE trading_behavior ADD COLUMN holding_period_preference TEXT;
ALTER TABLE trading_behavior ADD COLUMN allow_high_volatility INTEGER DEFAULT 0;
