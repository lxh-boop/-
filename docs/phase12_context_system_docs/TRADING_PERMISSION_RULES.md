# 用户股票交易权限规则

## 权限字段

```json
{
  "trading_permissions": {
    "main_board": true,
    "chinext": false,
    "star_market": false,
    "bse": false,
    "risk_warning": false,
    "stock_connect": false
  }
}
```

## 权限含义

| 字段 | 含义 |
|---|---|
| `main_board` | 沪深主板股票 |
| `chinext` | 创业板股票 |
| `star_market` | 科创板股票 |
| `bse` | 北交所股票 |
| `risk_warning` | ST、*ST、退市整理等风险警示股票 |
| `stock_connect` | 港股通标的 |

## 硬约束

1. 未开通对应权限的股票不得新增买入。
2. 已有但无权限的持仓不得继续加仓。
3. 已有持仓仍允许持有、减仓或卖出。
4. 权限约束优先于新闻调整分、用户调整分和 AI 解释。
5. 权限不满足时记录 `permission_denied:<permission>`。
6. 权限阻断释放的目标仓位由现有 Top10 分配器重新分配。
7. 每日模拟盘和历史回放使用相同规则。

## 板块识别优先级

1. 优先使用候选数据中的 `market_board`、`board`、`exchange` 等显式字段。
2. 没有显式字段时按股票代码识别：
   - `300/301`：创业板
   - `688/689`：科创板
   - `4/8/92` 常见北交所代码：北交所
   - 其他当前 A 股代码：沪深主板
3. `.HK` 或显式香港市场字段：港股通。
4. `ST`、`*ST`、退市整理状态作为附加权限，与所属板块权限同时校验。
