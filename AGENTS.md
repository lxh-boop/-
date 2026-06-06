# A 股每日股票评分与滚动训练 APP 项目阶段总结与 Codex 接手说明

## 一、项目定位

项目名称：

```text
A 股每日股票评分与滚动训练 APP
```

项目目标：

构建一个基于真实 A 股行情数据的机器学习股票评分系统。系统使用本地历史数据完成初始训练，使用 Tushare 获取最新行情进行每日增量更新，通过 Streamlit APP 展示每日股票排名、预测未来 5 日收益、上涨概率、综合评分、可信度和风险等级。

项目定位不是荐股系统，而是：

```text
机器学习 + 金融数据分析 + 量化因子建模 + APP 展示项目
```

页面必须始终保留免责声明：

```text
本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
```

------

## 二、当前总体架构

当前项目应该被整理为以下结构：

```text
stock_daily_app/
├── config.py
├── universe.py
├── data_local.py
├── data_tushare.py
├── alpha158.py
├── torch_models.py
├── torch_trainer.py
├── model_store.py
├── train_model.py
├── daily_incremental_update.py
├── app.py
├── local_config.py
├── scheduler_manager.py
├── requirements.txt
├── data/
├── models/
├── outputs/
└── logs/
```

核心分工：

```text
train_model.py
    只负责初始训练，不依赖 APP，不需要 Tushare Token。
    当前初始训练数据优先使用本地 Qlib 数据。

daily_incremental_update.py
    负责每日增量更新。
    读取本地已有模型，使用 Tushare Token 拉取最近行情，更新本地缓存，
    检查是否有新可监督样本，有则微调模型，没有则只预测最新排名。

app.py
    只负责页面展示和任务触发。
    APP 不应该在打开时自动全量训练。
    APP 支持填写 Tushare Token、验证连接、选择模型版本、执行每日增量更新、展示排名。

model_store.py
    管理 PyTorch 模型保存和读取。
    保存 latest 模型和历史版本模型。

alpha158.py
    计算 Alpha158 风格因子和未来 5 日标签。

universe.py
    统一管理股票池。
    当前需要改成 CSI300 股票池，而不是 12 只手写股票。
```

------

## 三、当前已经完成或基本完成的内容

### 1. 数据源方案已经明确

初始训练和每日更新分开：

```text
初始训练：
本地 Qlib 数据 → Alpha158 → PyTorch 训练 → 保存模型

每日更新：
Tushare 最新行情 → 更新本地缓存 → 计算 Alpha158 → 增量更新/预测 → 生成最新排名
```

当前已经下载 Qlib 数据到：

```text
D:\qlib_data\cn_data
```

注意：

不要在 `D:\qlib` 源码目录里测试 `import qlib`，否则会导入源码版 qlib，可能出现 `_libs.rolling` 缺失问题。应该在项目目录：

```text
D:\stock_daily_app
```

中运行 Qlib 相关测试或训练。

### 2. Qlib 数据可用于初始训练

当前 Qlib 数据是示例级数据，时间较短。已经检查过本地生成的 Alpha158 文件：

```text
data/train_feature_stock_data_alpha158.csv
shape = (2160, 175)
date nunique = 180
min date = 2020-01-02
max date = 2020-09-25
Feature count = 158
```

说明：

- Qlib 数据可以读取；
- Alpha158 计算成功；
- 特征数量 158 正确；
- 当前数据只有 180 个交易日；
- 训练脚本里不能强制要求 200 个交易日，否则会报错。

需要在 `train_model.py` 中将最低训练天数从 200 改成 80，例如：

```python
MIN_TRAIN_DAYS = 80
```

并打印：

```python
print(f"[Data] available labeled trading days = {len(dates)}")
print(f"[Data] labeled sample shape = {model_df.shape}")
print(f"[Data] labeled date range = {model_df['date'].min()} ~ {model_df['date'].max()}")
```

### 3. Alpha158 因子已经实现

`alpha158.py` 当前负责：

- 计算 K 线形态因子；
- 计算相对价格因子；
- 计算多窗口滚动因子；
- 构造未来 5 日收益标签；
- 构造未来 5 日上涨标签；
- 构造展示字段：
  - `ret_5`
  - `ret_20`
  - `vol_20`
  - `drawdown_20`

当前特征数已经验证为：

```text
158
```

有一些 pandas warning：

```text
PerformanceWarning: DataFrame is highly fragmented
```

这不是错误，只是性能提醒。后续可以优化为先用 dict 收集因子，再一次性 `pd.concat`。

### 4. PyTorch 模型已经设计

当前模型为 PyTorch MLP 多任务模型：

```text
Alpha158 因子输入
    ↓
MLP Backbone
    ↓
回归头：预测 future_5d_ret
分类头：预测 future_5d_up
```

相关文件：

```text
torch_models.py
torch_trainer.py
model_store.py
```

模型保存路径：

```text
models/torch_mlp/latest/torch_model_bundle.pt
models/torch_mlp/latest/metrics.json
models/torch_mlp/latest_info.json
models/torch_mlp/具体时间戳版本/
```

示例版本名：

```text
20260531_180423
```

`.pt` 是当前推荐格式，不需要强行改成 `.pkl`。如果确实要兼容，也应该读取 `.pt` 后用 joblib 重新保存 bundle，不能简单改后缀。

### 5. APP 页面已有雏形

当前 APP 已经包含：

- Tushare Token 输入；
- 验证连接；
- 保存 Token；
- 选择本地模型版本；
- 执行更新按钮；
- 每日自动重训练设置；
- 进度条；
- 排名展示区域；
- 模型指标展开区；
- 免责声明。

但当前 APP 还有几个需要修正的问题：

1. 按钮文案还可能是旧的“读取本地模型并刷新最新排名”，应改为“每日增量更新并生成排名”。
2. 进度条目前是基于预计时间，不代表真实任务阶段。
3. 页面显示“正在收尾 95%”不代表任务真的完成，只说明预计时间已经到了但后台进程还没退出。
4. CSI300 后不应该逐只股票调用 Tushare `pro_bar`，会非常慢。

------

## 四、当前最重要的未完成任务

### 任务 1：把股票池改成 CSI300

现在模型不能再只用 12 只股票，需要改为 CSI300。

要求：

```text
初始训练股票池 = CSI300
每日增量更新股票池 = CSI300
APP 最新每日股票评分排名 = CSI300 股票池预测结果
```

不要手写 300 只股票代码。应该新增或修正 `universe.py`，统一管理股票池。

推荐逻辑：

1. 优先读取本地缓存：

```text
data/csi300_stock_pool.csv
```

1. 如果没有缓存，优先从 Qlib 目录读取：

```text
D:\qlib_data\cn_data\instruments\csi300.txt
```

1. 如果 Qlib 没有 csi300 文件，再用 Tushare `index_weight` 获取 CSI300 成分股。
2. 用 Tushare `stock_basic` 补充股票名称。

`config.py` 应包含：

```python
UNIVERSE = "csi300"
CSI300_POOL_CACHE_PATH = r"data\csi300_stock_pool.csv"
QLIB_PROVIDER_URI = r"D:\qlib_data\cn_data"
USE_TUSHARE_INDEX_WEIGHT_FALLBACK = True
```

相关文件都应该通过 `get_stock_pool(...)` 获取股票池，而不是直接导入 `STOCK_POOL`。

需要修改：

```text
data_local.py
data_tushare.py
train_model.py
daily_incremental_update.py
app.py
```

### 任务 2：每日更新不能全量拉数据

当前卡在 95% 的主要原因很可能是：

```text
对 300 只股票逐个调用 Tushare pro_bar
```

这是错误的。CSI300 每日更新不能 300 只逐个请求。

正确做法：

```text
使用 Tushare pro.daily 按交易日一次性拉全市场日线，
然后筛选 CSI300 成分股。
```

每日更新不应该每次从 2020 年开始全量拉数据。

正确逻辑：

```text
1. 读取本地历史行情缓存 latest_raw_stock_data.csv；
2. 用 Tushare 只拉最近 N 个交易日，例如最近 3~10 个交易日；
3. 合并缓存并去重；
4. 用合并后的缓存计算 Alpha158；
5. 用已有模型预测最新排名；
6. 只有当新增了可监督样本时才微调模型。
```

注意：

今天的数据不能直接训练未来 5 日收益模型，因为今天没有未来 5 天后的真实收益。今天的数据只能用于预测。真正新增的可训练样本通常是 5 个交易日前那一天。

### 任务 3：新增快速 Tushare 日线获取函数

在 `data_tushare.py` 中新增函数：

```python
fetch_stock_pool_recent_daily_fast(...)
```

功能：

```text
按最近交易日调用 Tushare pro.daily；
一天一次请求；
获取全市场日线；
筛选 CSI300；
可选合并 adj_factor；
转为统一字段：
date, code, name, open, close, high, low, volume, amount, pct_chg, vwap, turnover
```

这比旧方式快很多：

```text
旧方式：300 只股票 × pro_bar 逐个请求
新方式：最近 N 个交易日 × pro.daily 全市场批量请求
```

### 任务 4：新增或修正 `daily_incremental_update.py`

每日更新脚本不要再全量重训。

它应该做：

```text
读取本地模型
读取本地历史行情缓存
快速拉取最近交易日行情
合并本地缓存
重新计算 Alpha158
检查新增可监督样本
有新增样本则微调模型 3~5 epoch
无新增样本则不保存新模型
用最新一日样本生成 ranking_latest.csv
```

输出文件：

```text
data/latest_raw_stock_data.csv
data/latest_feature_stock_data_alpha158.csv
outputs/ranking_latest.csv
outputs/ranking_YYYYMMDD_torch_mlp.csv
```

如果微调了模型，则保存：

```text
models/torch_mlp/新时间戳版本/
models/torch_mlp/latest/
```

### 任务 5：APP 加入 TopK 选择

APP 的“最新每日股票评分排名”需要加入选择展示 TopK。

侧边栏加入：

```python
topk_option = st.sidebar.selectbox(
    "选择展示 TopK",
    options=[10, 20, 30, 50, 100, 300, "全部"],
    index=3,
)
```

读取 ranking 后：

```python
if topk_option == "全部":
    ranking_display_source = ranking.copy()
else:
    ranking_display_source = ranking.head(int(topk_option)).copy()
```

排名表、柱状图、散点图都使用：

```python
ranking_display_source
```

但个股走势选择可以继续用全部 `ranking`，方便查 300 只股票。

APP 还应显示：

```text
当前排名股票数
当前展示数量
当前 Universe
当前模型版本
```

### 任务 6：修正 APP 进度条含义

当前 APP 的进度条是基于时间估计，不是真实任务进度。

不能再显示：

```text
正在收尾
```

因为 95% 不代表真实收尾，只代表预计时间已经用完，后台任务还没结束。

应改为：

```text
已超过预计时间，后台任务仍在运行，请等待或查看日志
```

`get_stage_by_progress()` 应根据 `elapsed` 和 `estimated_seconds` 判断：

```python
if elapsed > estimated_seconds:
    return "已超过预计时间，后台任务仍在运行，请等待或查看日志"
```

并且后台进程的 stdout/stderr 不要用 `PIPE` 堵住，应写入日志文件：

```text
logs/rolling_update_app.log
```

否则子进程输出太多会卡死。

------

## 五、当前建议的运行顺序

Codex 接手后，请先不要一次性大改所有功能。按下面顺序做。

### 第 1 步：确认当前项目能初始训练

运行：

```powershell
cd D:\stock_daily_app
python train_model.py --source qlib
```

如果报可用交易日太少，把 `MIN_TRAIN_DAYS` 改为 80。

成功后应生成：

```text
models/torch_mlp/latest/torch_model_bundle.pt
models/torch_mlp/latest/metrics.json
models/metrics.pkl
outputs/evaluation_metrics.csv
```

### 第 2 步：实现并测试 CSI300 股票池

删除旧缓存：

```powershell
Remove-Item data\csi300_stock_pool.csv -ErrorAction SilentlyContinue
```

运行训练或单独测试 `universe.py`，确认输出：

```text
CSI300 股票数量约 300
```

如果 Qlib 的 csi300 文件可用，优先使用 Qlib。否则使用 Tushare fallback。

### 第 3 步：修正每日增量更新

确认 `daily_incremental_update.py` 不再调用旧的逐只股票 `pro_bar` 全量拉取方式。

应调用：

```python
fetch_stock_pool_recent_daily_fast(...)
```

先终端测试：

```powershell
python daily_incremental_update.py --token 你的TushareToken --base-version latest
```

成功后应生成：

```text
data/latest_raw_stock_data.csv
data/latest_feature_stock_data_alpha158.csv
outputs/ranking_latest.csv
```

### 第 4 步：修正 APP 调用脚本

确认 `app.py` 中：

```python
ROLLING_UPDATE_SCRIPT = BASE_DIR / "daily_incremental_update.py"
```

不要再调用：

```python
rolling_update.py
```

按钮改为：

```text
每日增量更新并生成排名
```

### 第 5 步：增加 TopK 选择

APP 侧边栏新增 TopK 选择，排名表和图表只展示所选 TopK。

### 第 6 步：修正进度条

进度条继续可以按时间估计，但必须明确它是估计。

不要显示“正在收尾”。

超过预计时间时显示：

```text
已超过预计时间，后台任务仍在运行，请等待或查看日志
```

后台进程输出写入：

```text
logs/rolling_update_app.log
```

不要用 `stdout=PIPE` 且不读取。

------

## 六、需要保留的设计原则

### 1. APP 不应该打开就训练

APP 打开时只读取已有文件：

```text
models/
outputs/ranking_latest.csv
```

只有用户点击按钮，才执行每日增量更新。

### 2. 初始训练和每日更新分开

```text
train_model.py
    本地历史数据初始训练

daily_incremental_update.py
    Tushare 最近行情每日增量更新

app.py
    展示和触发
```

### 3. 不要数据穿越

今天的数据不能训练未来 5 日收益标签。

训练样本必须经过：

```python
prepare_model_data(...)
```

自动删除没有 `future_5d_ret` 的样本。

### 4. 股票池统一

不要在不同文件里写不同股票池。

所有文件都应该通过：

```python
from universe import get_stock_pool
```

获取股票池。

### 5. ranking_latest.csv 是 APP 展示核心

APP 最终展示以：

```text
outputs/ranking_latest.csv
```

为准。

字段至少包括：

```text
rank
date
code
name
close
pred_5d_ret
up_prob
score
confidence
risk_level
model_name
ret_5
ret_20
vol_20
drawdown_20
```

### 6. 所有 token 不能写死

Tushare Token 只能来自：

- APP 输入框；
- 本地配置 `local_app_config.json`；
- 环境变量 `TUSHARE_TOKEN`。

不要硬编码到代码里。

------

## 七、最终目标效果

最终 APP 应该是这样：

```text
左侧：
- Tushare Token 输入
- 验证连接
- 保存 Token
- 选择本地模型版本
- 每日增量更新并生成排名
- TopK 展示选择
- 是否开启每日自动更新
- 自动更新时间

主页面：
- 项目标题
- 免责声明
- 模型状态
- 当前 Universe = CSI300
- 当前模型版本
- 当前排名股票数量
- 当前展示 TopK
- 每日股票评分排名表
- 综合评分柱状图
- 预测收益 vs 上涨概率散点图
- 个股走势
- 模型指标
```

最终系统流程：

```text
本地 Qlib / CSV 历史数据
    ↓
train_model.py 初始训练
    ↓
保存本地模型
    ↓
APP 读取模型
    ↓
Tushare 拉取最近交易日行情
    ↓
更新本地行情缓存
    ↓
如有新标签样本则微调模型
    ↓
生成 CSI300 每日排名
    ↓
APP 根据 TopK 展示结果
```

------

## 八、给 Codex 的直接任务提示

请先完整检查当前项目目录 `D:\stock_daily_app`，不要假设所有文件已经正确实现。然后按以下顺序修改：

1. 检查 `config.py`，加入或确认 `UNIVERSE="csi300"`、`QLIB_PROVIDER_URI`、`CSI300_POOL_CACHE_PATH`。
2. 新增或修正 `universe.py`，实现统一 CSI300 股票池读取。
3. 修改 `data_local.py`，让初始训练使用 CSI300。
4. 修改 `data_tushare.py`，新增 `fetch_stock_pool_recent_daily_fast`，每日更新不能再 300 只逐个 `pro_bar`。
5. 修改 `daily_incremental_update.py`，让它只拉最近交易日数据，合并本地缓存，增量微调或跳过训练，然后生成 ranking_latest.csv。
6. 修改 `app.py`：
   - 调用 `daily_incremental_update.py`；
   - 按钮改为“每日增量更新并生成排名”；
   - 增加 TopK 选择；
   - 所有表格和图表使用 TopK 筛选结果；
   - 修正进度条文案，不要误导性显示“正在收尾”；
   - 子进程输出写日志，不要 PIPE 堵塞。
7. 先运行：
   `python train_model.py --source qlib`
8. 再运行：
   `python daily_incremental_update.py --token 用户填入的Token --base-version latest`
9. 最后运行：
   `streamlit run app.py`
10. 每一步修改后都要运行基本测试，确保不会破坏已有功能。

不要加入新闻、RAG、大模型解释、复杂回测。当前阶段只做：
CSI300 股票池、快速每日增量更新、TopK 展示、APP 体验修复。