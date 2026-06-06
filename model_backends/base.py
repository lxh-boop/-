from __future__ import annotations


class BaseModelBackend:
    backend_name: str = "base"

    def fit(self, train_df, valid_df, feature_cols):
        raise NotImplementedError

    def predict(self, df, feature_cols):
        raise NotImplementedError

    def save(self, save_dir):
        raise NotImplementedError

    def load(self, save_dir):
        raise NotImplementedError
