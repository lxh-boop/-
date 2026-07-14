# 用户交易权限数据字典

## 数据源

当前权限保存到用户级画像文件：

```text
outputs/users/<user_id>/user_profile.json
```

数据库中的原有用户画像、风险测评和投资目标保持不变。加载用户上下文时，系统将数据库数据与用户画像 JSON 中的权限字段合并。

## `trading_permissions`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `main_board` | bool | true | 沪深主板买入权限 |
| `chinext` | bool | false | 创业板买入权限 |
| `star_market` | bool | false | 科创板买入权限 |
| `bse` | bool | false | 北交所买入权限 |
| `risk_warning` | bool | false | 风险警示股票买入权限 |
| `stock_connect` | bool | false | 港股通买入权限 |

## 执行诊断新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `trading_permissions` | object | 本次运行使用的权限快照 |
| `permission_blocked_count` | int | 因权限不足被阻断的候选数量 |
| `permission_blocked_candidates` | list | 阻断股票、所需权限及原因 |
| `permission_frozen_weight` | float | 无权限已有持仓保留或压缩的仓位 |
| `allocation_target_ratio_after_permission` | float | 扣除冻结仓位后的可重新分配目标 |
| `engine_permission_blocks` | list | 执行引擎第二层校验阻断记录 |

## 错误原因格式

```text
permission_denied:chinext
permission_denied:star_market
permission_denied:bse
permission_denied:risk_warning
permission_denied:stock_connect
```
