# Model Specification

本文档说明当前模型、特征、标签、排名和每日更新行为。

## 当前使用模型

当前运行产物中保留的最佳外部模型是 `chronos_bolt_small`。

实现和产物：

- `model_zoo/registry.py`：注册 `chronos_bolt_small`。
- `model_zoo_backend.py`：Model Zoo 后端统一预测和排名输出。
- `models/external_zoo/chronos/chronos_bolt_small/`：本地模型文件。
- `models/external_zoo/metadata.json`：模型下载与状态元数据。
- `outputs/ranking_latest.csv`：当前首页展示排名，`model_name=chronos_bolt_small`。

旧本地 MLP 训练链路已经移除，当前主流程不再提供本地监督训练、微调或模型存取入口。

## 特征

基础特征是 Alpha158 风格因子，附加展示和标签字段。

生成位置：

- `alpha158.py`：`add_alpha158_features(...)`、`get_alpha158_feature_cols(...)`
- `news_features.py`：新闻事件特征，受 `config.ENABLE_NEWS_FEATURES` 控制。

字段类型：

- 价格相对因子、K 线形态、多窗口滚动统计。
- 展示字段：`ret_5`、`ret_20`、`vol_20`、`drawdown_20`。
- 如果开启新闻特征，会追加 `NEWS_EVENT_FEATURE_COLUMNS`。

## 标签

预测窗口是未来 5 日。

标签：

- `future_5d_ret = close.shift(-5) / close - 1`
- `future_5d_up = future_5d_ret > 0`
- `future_5d_score`：按日横截面标准化后的未来收益标签，裁剪范围由 `LABEL_ZSCORE_CLIP` 控制。

重要边界：

- 今天没有未来 5 日真实收益，不能作为监督训练样本。
- 当前每日更新只使用最新可得窗口生成预测排名，不做旧本地训练链路的增量训练。

实现位置：

- `alpha158.py`
- `daily_incremental_update.py`

## 排名生成

排名核心字段：

```text
rank, date, code, name, close, pred_5d_ret, raw_score, up_prob,
score, confidence_score, confidence, risk_score, risk_level, model_name
```

`score` 是横截面分位数，越高排名越靠前。`rank=1` 是最高排名。

可信度：

- 概率强度
- 排名位置
- 校准质量
- 风险扣减
- 波动扣减

风险：

- 20 日波动
- 20 日回撤
- 流动性
- 近期收益冲击
- 新闻风险事件

实现位置：

- `ranking_schema.py`
- `confidence_scoring.py`
- `risk_scoring.py`
- `daily_incremental_update.py`
- `model_zoo_backend.py`

## 每日增量更新

目标流程：

```text
读取本地历史行情缓存
    -> Tushare 最近交易日行情
    -> 合并去重
    -> 计算 Alpha158 / 新闻事件特征
    -> 外部模型生成预测
    -> 生成 ranking_latest.csv
```

关键约束：

- 每日更新不应从 2020 年开始全量拉取。
- CSI300 不应逐只 `pro_bar` 拉取。
- 当前快速接口按交易日调用 `pro.daily` 后筛选股票池。

实现位置：

- `data_tushare.py`：`fetch_stock_pool_recent_daily_fast(...)`
- `daily_incremental_update.py`：`prepare_latest_feature_data(...)`
- `model_zoo_backend.py`

## 当前已知实现状态

- `chronos_bolt_small` 是当前保留的最佳外部模型和页面最新排名来源。
- 概率校准如果没有足够可用样本，会退化为 identity 或横截面排序 fallback。
