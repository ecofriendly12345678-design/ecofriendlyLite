# Polymarket 实时纸上套利 Agent —— 设计文档 (v1)

- 日期: 2026-07-08
- 状态: 已批准,待实施
- 上游依赖: [`Polymarket/polymarket-cli`](https://github.com/Polymarket/polymarket-cli)(通过 `polymarket -o json` 作为只读数据/执行层)

## 1. 目标与非目标

### 目标
- 构建一个 **Python** agent,盯住一小撮**真实 Polymarket 市场**,以**实时轮询循环**运行。
- 检测**一致性/套利机会**:一整套互斥结果的最优卖价之和 `< $1`。
- 对着**真实订单簿深度**做**模拟成交(paper trading)**,盈亏可信。
- 维护一个本地**虚拟账本**,持续按实时市价重估(mark-to-market)。
- 覆盖**二元(YES+NO)**市场与 **neg-risk 多结果事件**。

### 非目标(v1 明确不做)
- ❌ 不下真实订单、不碰真实资金、**不需要私钥/钱包**。
- ❌ 不做全市场扫描(v1 只跑配置的 watchlist)。
- ❌ 不做 LLM 决策、不做跨市场语义关联(如"X 赢" vs "X 赢 5+")。
- ❌ 不做动量/均值回归等需要统计调参的策略。
- ❌ 不用 WebSocket 流(CLI 不支持;v1 用轮询)。

## 2. 安全性(结构性保证)

v1 对 Polymarket **完全只读**。代码只调用 CLI 的读取命令:`markets`、`events`、`clob book`、`clob midpoint`/`midpoints`、`clob books`。**永远不会**调用 `clob create-order` / `clob market-order` / `approve` / `ctf` 等任何写入命令。因此**下真实订单在结构上不可能**——这是一个代码级不变量,implementation plan 里应有测试守护它。

## 3. 核心策略:一致性/套利信号

### 原理
每个结果 share 结算时:发生赔付 $1,不发生赔付 $0。一组**互斥且完备**的结果(binary = YES/NO;neg-risk = 所有候选)中**恰好一个**会赢。因此持有"每个结果各 1 股"这一整套,结算时**必得 $1**,与结果无关。

所以这一套的公允价 = **$1**。若买下整套的成本 `< $1`,即锁定无风险利润。

### 判据
设一套结果的最优卖价(best ask,即你买入需付的价)为 `a_1, a_2, …, a_n`:

```
cost = Σ a_i
edge = 1 - cost
若 edge > (min_edge_threshold + est_fee)  →  生成 Opportunity
```

- `best ask`:订单簿中你能立即成交的最低卖价。
- `min_edge_threshold`:过滤蝇头小利/价格噪音(可配)。
- `est_fee`:预估手续费与滑点缓冲(可配)。

### 两种市场
- **Binary**:一套 = {YES token, NO token},n = 2。
- **neg-risk 多结果事件**:一套 = 该事件下所有互斥结果的 token,n = 结果数。需要能枚举事件的全部结果及其 token_id。

## 4. 架构

### 数据流(每一轮 tick)
```
读取 watchlist
  → 对每个市场/事件,批量抓取订单簿 (clob books)
  → scanner 计算 Σ(best_ask),得出 edge
  → 按风控过滤 (min_edge / 单笔上限 / 并发上限 / 资金上限)
  → fills 逐档模拟真实成交,算真实平均价;深度不足则拒绝
  → portfolio 记录模拟持仓,写入 SQLite
  → 用实时 midpoint 重估所有持仓 (mark-to-market)
  → report 打印状态
  → sleep(interval),下一轮
```

### 模块划分(每个可独立测试)

| 模块 | 职责 | 关键接口(示意) |
|---|---|---|
| `cli.py` | **唯一**知道 `polymarket` 二进制的地方。封装子进程、`-o json`、超时、错误(非零退出→`{"error"}`)。 | `get_market(id)`, `get_event(id)`, `get_books(token_ids)`, `get_midpoints(token_ids)` |
| `models.py` | 领域类型(dataclass)。`ResultSet` = 一组互斥完备结果(binary 或 neg-risk 事件)及其 token_id 列表。 | `Market`, `Outcome`, `OrderBook`, `BookLevel`, `ResultSet`, `Opportunity`, `Position`, `Fill` |
| `scanner.py` | 由已抓取数据计算套利信号,产出 `Opportunity`。**纯逻辑**。 | `evaluate(sets: list[ResultSet]) -> list[Opportunity]` |
| `fills.py` | 沿订单簿深度逐档计算目标数量的平均成交价+实际成交量;深度不足返回拒绝。**纯函数**。 | `simulate_fill(book, target_size) -> Fill \| None` |
| `portfolio.py` | 虚拟账本(SQLite):起始资金、持仓、已实现/未实现盈亏、风控执行。 | `can_open(opp)`, `open_position(fills)`, `mark_to_market(midpoints)`, `summary()` |
| `agent.py` | 实时循环编排;支持 `--once`(单轮)与默认循环。 | `run(config)` |
| `report.py` | 打印账户状态、机会、成交、盈亏。 | `render(portfolio_summary)` |
| `config.py` + `config.yaml` | 加载配置:watchlist、阈值、资金、间隔、风控。 | `load(path) -> Config` |

### 目录结构
```
polymarket-agent/
  pyproject.toml            # 依赖:pyyaml (+ pytest)
  config.yaml               # 用户配置
  src/agent/
    __init__.py
    cli.py
    models.py
    scanner.py
    fills.py
    portfolio.py
    agent.py
    report.py
    config.py
  tests/
    test_scanner.py
    test_fills.py
    test_cli.py             # 用假子进程/fixture JSON
    test_portfolio.py
    test_safety.py          # 断言不含任何写入命令调用
  docs/superpowers/specs/
    2026-07-08-polymarket-paper-arb-agent-design.md
```

## 5. 运行模式(实时)

- **主模式:实时循环**。默认聚焦 `config.yaml` 的 **watchlist**(v1 只跑少数几个市场/事件)。
- 轮询间隔 `poll_interval_seconds` 可配(默认建议 5–10s)。CLI 无流式,"实时" = 快速轮询。
- 利用 CLI 的**批量命令**(`clob books "T1,T2,..."`、`clob midpoints`)把每轮压缩为很少几次子进程调用。
- `--once` 标志:只跑一轮用于测试/冒烟。
- 未来升级路径:`cli.py` 接口层不变,可在其背后换成直连 SDK 的 WebSocket 流。

## 6. 数据模型与持久化

- 虚拟账本用 **SQLite**(单文件,便于查询与重启后保留状态)。
- 表:`positions`(持仓)、`fills`(成交明细)、`opportunities`(发现记录,便于事后统计机会频率)。
- 每轮结束把重估后的盈亏快照写入,便于观察曲线。

## 7. 配置(`config.yaml` 示意)
```yaml
virtual_capital_usd: 1000        # 起始虚拟资金
poll_interval_seconds: 5
min_edge: 0.01                   # 至少便宜 1¢/套 才动手
est_fee: 0.00                    # 预估费+滑点缓冲(Polymarket 现货费率填实测值)
max_notional_per_trade_usd: 50
max_concurrent_positions: 10
watchlist:                       # v1 先手填;跑起来后用 `polymarket markets list` 挑活跃市场
  - type: binary
    ref: "<market-slug-or-id>"
  - type: event
    ref: "<event-id>"
```

## 8. 错误处理

- 每个 CLI 调用包裹:非零退出、超时、JSON 解析失败 → 抛结构化异常。
- scanner/agent 对单个市场失败**跳过并继续**(市场可能已关闭、深度为空、临时网络错误),不让整个循环崩溃。
- `fills.py` 对空/浅订单簿返回"拒绝"而非异常。
- 循环层捕获意外异常并记录,退避后继续(不静默吞掉)。

## 9. 验收标准

1. **单测 `scanner`**:对一套定价 $0.97 的结果报警;对 $1.00 忽略;neg-risk 三结果 $0.30+$0.30+$0.35=$0.95 报警。
2. **单测 `fills`**:多档订单簿平均价计算正确(逐档吃单);目标数量 > 总深度时返回拒绝。
3. **单测 `safety`**:静态断言代码不含任何写入类 CLI 子命令字符串(`create-order`、`market-order`、`approve`、`ctf split/merge/redeem`)。
4. **实时冒烟**:对真实 watchlist 只读跑起来,持续打印机会/模拟成交;账本重估的合计盈亏 = 各持仓单独重估之和(对账一致)。

## 10. 已知局限(诚实预期)

- 真正无风险套利在 Polymarket 上**罕见且微小**,会被快速吃掉。v1 的价值在于**正确的检测+执行闭环、学习市场机制、统计机会频率**,而非稳定盈利。
- 可把 `min_edge` 调低以观察"准套利",学习价值主要在此。
- 轮询非 tick 级实时;对本策略足够,但不适合高频。

## 11. 未来扩展(不在 v1)
- 全市场扫描;WebSocket 流式行情;LLM 判断层;跨市场语义关联;真实下单(需私钥、确认流程、严格资金上限)。
