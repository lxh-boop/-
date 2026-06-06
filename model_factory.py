from sklearn.ensemble import (
    RandomForestClassifier,
    RandomForestRegressor,
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
)


def create_kline_models(model_name: str):
    """
    根据模型名称创建：
    1. 回归模型：预测 future_5d_ret
    2. 分类模型：预测 future_5d_up

    daily_update.py 不直接关心具体模型细节。
    """

    model_name = model_name.lower().strip()

    if model_name == "random_forest":
        reg_model = RandomForestRegressor(
            n_estimators=400,
            max_depth=8,
            min_samples_leaf=20,
            random_state=42,
            n_jobs=-1
        )

        cls_model = RandomForestClassifier(
            n_estimators=400,
            max_depth=8,
            min_samples_leaf=20,
            random_state=42,
            n_jobs=-1
        )

        return reg_model, cls_model

    if model_name == "extra_trees":
        reg_model = ExtraTreesRegressor(
            n_estimators=400,
            max_depth=8,
            min_samples_leaf=20,
            random_state=42,
            n_jobs=-1
        )

        cls_model = ExtraTreesClassifier(
            n_estimators=400,
            max_depth=8,
            min_samples_leaf=20,
            random_state=42,
            n_jobs=-1
        )

        return reg_model, cls_model

    if model_name == "gradient_boosting":
        reg_model = GradientBoostingRegressor(
            n_estimators=300,
            learning_rate=0.03,
            max_depth=3,
            random_state=42
        )

        cls_model = GradientBoostingClassifier(
            n_estimators=300,
            learning_rate=0.03,
            max_depth=3,
            random_state=42
        )

        return reg_model, cls_model

    if model_name == "lightgbm":
        try:
            from lightgbm import LGBMRegressor, LGBMClassifier
        except ImportError as exc:
            raise ImportError(
                "当前环境没有安装 lightgbm，请先运行：pip install lightgbm"
            ) from exc

        reg_model = LGBMRegressor(
            n_estimators=500,
            learning_rate=0.03,
            max_depth=-1,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1
        )

        cls_model = LGBMClassifier(
            n_estimators=500,
            learning_rate=0.03,
            max_depth=-1,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1
        )

        return reg_model, cls_model

    raise ValueError(
        f"不支持的模型名称：{model_name}。"
        f"可选模型：random_forest, extra_trees, gradient_boosting, lightgbm"
    )


def model_supports_predict_proba(cls_model):
    """
    检查分类模型是否支持 predict_proba。
    如果后面换成某些模型不支持 predict_proba，可以在 daily_update.py 里做兼容。
    """
    return hasattr(cls_model, "predict_proba")