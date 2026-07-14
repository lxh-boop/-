ALTER TABLE paper_nav_history ADD COLUMN composite_nav REAL NOT NULL DEFAULT 1;
ALTER TABLE paper_account ADD COLUMN composite_nav REAL NOT NULL DEFAULT 1;
ALTER TABLE paper_account_snapshot ADD COLUMN composite_nav REAL NOT NULL DEFAULT 1;
ALTER TABLE paper_trading_settings ADD COLUMN target_cash_ratio REAL NOT NULL DEFAULT 0.05;
ALTER TABLE paper_trading_settings ADD COLUMN maximum_cash_ratio REAL NOT NULL DEFAULT 0.30;
