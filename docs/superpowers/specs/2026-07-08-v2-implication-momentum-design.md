# v2:跨市场蕴含套利 + 动量策略 —— 设计文档

- 日期: 2026-07-08
- 状态: 已批准,待实施(用户选定"一致性 + 动量"组合并要求直接进入 spec → plan)
- 前置: v1(完整集合套利,spec `2026-07-08-polymarket-paper-arb-agent-design.md`)已完成实施
- 交付方式: **两个独立的实施计划**,按依赖顺序执行
  - **v2a**: 策略插件化重构 + 蕴含套利(小改动,先见收益)
  - **v2b**: tick 数据采集 + 回测器 + 动量策略(基础设施 + 首个方向性策略)

## 0. 总原则(继承 v1,新增两条)

- 仍然 **100% 只读、纸上交易**:不下真实订单、无钱包。`tests/test_safety.py` 结构性守护不变。
- 所有资金运算仍然 `Decimal`;token id 仍然规范化十进制字符串。
- **新增铁律 1(动量)**:动量策略必须先通过回测验证参数后才允许在实时纸上循环中启用。配置默认 `momentum.enabled: false`。
- **新增铁律 2(蕴含)**:蕴含关系只用手工白名单(`implications.yaml`),不用 LLM 或字符串匹配自动推断。每条关系必须人工核对**双方市场的结算条款**(结算来源、时间窗、边界条件)后才可加入。

## 1. 目标与非目标

### 目标
- **策略插件化**:把 v1 硬编码在 `tick()` 里的完整集合逻辑重构为统一的 Strategy 协议,三个策略(complete_set / implication / momentum)以插件共存。
- **蕴含套利**:检测 A ⟹ B 关系下的定价违规(P(A) > P(B)),用"买 NO(A) + 买 YES(B)"锁定保底 $1 的赔付。
- **资金分桶**:每个策略独立资金上限,仓位带策略标签,盈亏按策略归因。
- **tick 数据采集**:实时循环顺手把订单簿快照存入 SQLite,为回测积累带深度的数据。
- **回测器**:重放历史数据,跑与实时完全相同的策略接口;支持参数网格扫描。
- **动量策略**:含入场信号、卖方向成交模拟、止盈/止损/时间止损退出逻辑。

### 非目标(v2 明确不做)
- ❌ 全市场扫描(仍限 watchlist);❌ WebSocket;❌ LLM 决策;❌ 真实下单。
- ❌ 做市策略、热门-冷门偏差策略(未来 v3 候选)。
- ❌ 蕴含关系的自动发现。

## 2. 蕴含套利(v2a)

### 数学结构
设 A ⟹ B(A 是更难/更窄的结果)。组合 = 每单位买 1 股 NO(A) + 1 股 YES(B):

| 结局 | NO(A) | YES(B) | 合计赔付 |
|---|---|---|---|
| A ∧ B | 0 | 1 | **$1** |
| ¬A ∧ B | 1 | 1 | **$2** |
| ¬A ∧ ¬B | 1 | 0 | **$1** |
| A ∧ ¬B | 逻辑上不可能(A ⟹ B) | | |

**保底 $1/单位,上限 $2/单位**。信号:`ask(NO_A) + ask(YES_B) < 1 − min_edge − est_fee` → 与 v1 完整集合套利同构,复用 `ResultSet`(新 `kind="implication"`)、`SetPurchase`、`fills.plan_set_purchase`、账本的 `guaranteed_payout = n_sets`(此处为保底而非精确值,字段语义:**最低**保证赔付)。

### 关系配置 `implications.yaml`(项目根)
```yaml
implications:
  - if: <market slug 或 conditionId>     # A:更难的结果
    then: <market slug 或 conditionId>   # B:更容易的结果
    note: "为什么 A ⟹ B;结算条款核对记录 + 日期"
```
- 加载时解析双方市场(`cli.get_market`),A 取 NO token(`clobTokenIds[1]`),B 取 YES token(`clobTokenIds[0]`)。
- 任一市场不可交易(closed/inactive)→ 跳过该关系并警告。
- **风险提示写入 spec 与 README**:本策略唯一的实质风险是"关系判断错误或结算条款不对齐"(如 A 比 B 晚结算、结算来源不同)。发生 A ∧ ¬B 时赔付 $0。白名单 + note 字段强制记录核对过程就是为此。

### 蕴含集合不适用 v1 的 Σmid 完备性检查
完整集合的 sanity guard(Σmid ≈ 1)不适用:一致定价下 mid(NO_A)+mid(YES_B) = 1 + (P_B − P_A) ∈ [1, 2],而套利信号本身就是这个和跌破 1。蕴含集合跳过该 guard,以白名单人工核对替代。

## 3. 策略插件架构(v2a 落地,v2b 复用)

### Strategy 协议(`src/agent/strategies/__init__.py`,接口精确固定)
```python
class StrategyProtocol(Protocol):
    name: str                                            # "complete_set" | "implication" | "momentum"
    def required_tokens(self) -> list[str]: ...          # 本策略需要订单簿的 token(规范化十进制)
    def propose_entries(
        self, books: dict[str, OrderBook], ctx: TickContext,
    ) -> list[EntryProposal]: ...
    def propose_exits(
        self, books: dict[str, OrderBook], open_positions: list[OpenPosition], ctx: TickContext,
    ) -> list[ExitProposal]: ...
```
- `TickContext`:`(now: datetime, config_section: dict)` —— 当前 tick 时间(便于回测注入虚拟时间)与该策略的配置段。
- `EntryProposal(strategy: str, purchase: SetPurchase, reason: str)` —— 入场统一为"买一篮子 token"。完整集合篮子=全套结果;蕴含篮子=NO_A+YES_B;动量篮子=单 token。`SetPurchase` 增加字段 `payout_floor_per_set: Decimal`(完整集合/蕴含=1,动量=0)。
- `ExitProposal(position_id: int, sell_fills: tuple[Fill, ...], reason: str)` —— 平仓卖出(沿 bids 成交)。complete_set/implication 持有到结算,`propose_exits` 返回 `[]`。
- `OpenPosition`:从账本读出的开放仓位视图 `(id, strategy, set_id, opened_at, n_sets, total_cost, legs: [(token_id, qty, avg_price)])`。
- 主循环 `tick()` 重构为:对每个启用策略 → 收集 `required_tokens` 并集 → 批量取书 → 依次调 `propose_exits`(先平后开)→ `propose_entries` → 风控(分桶)→ 账本 → MTM。**回测器驱动完全相同的接口。**

### 资金分桶与账本扩展
- `config.yaml` 新增:
```yaml
strategies:
  complete_set: { enabled: true, bucket_usd: 500 }
  implication:  { enabled: true, bucket_usd: 300, relations_file: implications.yaml }
  momentum:     { enabled: false, bucket_usd: 200, params: { ...见 §5 } }
```
- `positions` 表加 `strategy TEXT NOT NULL` 列;`can_open` 校验改为按策略桶:`该策略未平仓成本 + 本次成本 ≤ bucket_usd`,同时保留全局 cash 与 max_concurrent 检查。
- `Summary` 增加 `by_strategy: dict[str, StrategySummary]`(各桶已用资金、开仓数、未实现/已实现盈亏)。
- 平仓支持:`portfolio.close_position(position_id, sell_fills, reason)` → 记录 proceeds、`realized_pnl = proceeds − total_cost`、`status='closed'`;现金公式更新为 `cash = starting − Σ(open 成本) + Σ(closed 的 realized_pnl + closed 的成本回笼)`,即 `starting − Σ(open.total_cost) + Σ(closed.proceeds − closed.total_cost) `… 统一为:`cash = starting − Σ(all.total_cost) + Σ(closed.proceeds)`。(v2a 先加列与公式,平仓函数在 v2b 用到;v2a 一并实现并测试,避免 v2b 改两次 schema。)

## 4. 数据采集与回测器(v2b)

### tick 记录器
- 表 `book_snapshots(id, ts TEXT, token_id TEXT, bids TEXT, asks TEXT)` —— bids/asks 存 JSON,**只存前 5 档**(足够动量回测的成交模拟,控制体积)。
- 实时循环每 tick 对所有已取订单簿写一行/每 token。watchlist 规模(≤ 50 token × 5s 轮询)下 SQLite 完全可承受;提供 `python -m agent.prune --keep-days 30` 清理工具。
- `price-history` 回填(`cli.get_price_history(token_id, interval, fidelity)` 新增只读方法,子命令 `clob price-history` 加入 cli.py 允许列表):仅价格无深度,存表 `price_history(ts, token_id, price)`,用于长回看期的信号研究;回测成交模拟只用 `book_snapshots`。

### 回测器(`src/agent/backtest.py`)
- `BacktestFeed(db_path, start, end)`:按 ts 分组重放 `book_snapshots` → 每步产出 `dict[token_id, OrderBook]` + 虚拟时间。
- `run_backtest(strategy, feed, starting_capital, params) -> BacktestResult`:用**内存版账本**(与 SQLite 版同一套风控逻辑,复用同一类,db_path=":memory:")驱动与实时循环完全相同的 `propose_entries/propose_exits`。
- `BacktestResult`:`(trades, equity_curve, total_return, win_rate, max_drawdown, n_trades)`。
- 网格扫描:`sweep(strategy_factory, feed, param_grid) -> list[(params, BacktestResult)]`,按 total_return 排序输出表格。
- **确定性**:同一数据 + 同一参数 → 结果逐字节一致(禁止随机数;时间来自数据)。

## 5. 动量策略(v2b)

### 信号(二元市场技巧:永远只做多)
YES 下跌 ⇔ NO 上涨,因此双向趋势都表达为**买入正在上涨的那个 token**,无需卖空。多结果事件同理,各 token 独立评估。

- **入场**(对 watchlist 内每个 token):
  - 回看收益 `r = (p_now − p_lookback) / p_lookback ≥ entry_return_threshold`(p 取 mid);
  - 流动性过滤:`spread ≤ max_spread` 且 best-ask 深度 ≥ 本次买入量;
  - 价格区间:`price_min ≤ p_now ≤ price_max`(极端价格无空间);
  - 该 token 无未平仓动量仓位;
  - 桶内资金足够 `position_usd`。
- **退出**(每 tick 检查):止盈 `mid ≥ entry_avg × (1 + take_profit)`;止损 `mid ≤ entry_avg × (1 − stop_loss)`;时间止损 `持仓 ≥ max_hold_hours`;市场关闭/订单簿消失 → 按可得 bids 强平。
- **卖方向成交**:`fills.walk_book_sell(bids, qty) -> proceeds | None`(沿 bids 逐档,深度不足时部分成交按可得量,剩余按 0 计入——保守)。

### 默认参数(config,全部可回测扫描;上线前必须以回测结果覆盖)
```yaml
params:
  lookback_minutes: 60
  entry_return_threshold: 0.05
  price_min: 0.10
  price_max: 0.90
  max_spread: 0.03
  take_profit: 0.10
  stop_loss: 0.05
  max_hold_hours: 24
  position_usd: 20
```

## 6. 文件结构(v2 完成后)
```
src/agent/
  strategies/
    __init__.py        # StrategyProtocol, EntryProposal, ExitProposal, TickContext, OpenPosition
    complete_set.py    # v1 逻辑迁入(v2a)
    implication.py     # 蕴含套利(v2a)
    momentum.py        # 动量(v2b)
  recorder.py          # book_snapshots 写入 + prune(v2b)
  backtest.py          # BacktestFeed / run_backtest / sweep(v2b)
  (cli.py 增加 get_price_history;fills.py 增加 walk_book_sell;portfolio.py 增加策略桶/平仓)
implications.yaml
tests/ (每个新模块对应 test_*.py;策略协议一致性测试;回测确定性测试)
```

## 7. 错误处理(增量)
- 蕴含关系解析失败(市场下架等)→ 警告并跳过该关系,其余照常。
- 记录器写库失败 → 警告并继续(数据缺口可容忍,交易不受影响)。
- 动量退出时 bids 为空 → 保留仓位并警告,下 tick 重试;市场 closed → 按 0 强平并记录异常标签。
- 回测数据存在时间缺口 → 正常推进(缺口即无 tick),不插值。

## 8. 验收标准
### v2a
1. 策略协议回归:重构后 v1 全部既有测试仍绿;complete_set 策略行为与 v1 tick 等价(同一 fixture 同一结果)。
2. 蕴含:fixture(ask_NO_A=0.44, ask_YES_B=0.52,和=0.96)→ 报警并按保底 $1 建仓;(0.50+0.52=1.02)→ 忽略。
3. 分桶:策略桶用满后该策略新机会被拒且记录原因;另一策略不受影响。
4. 平仓函数:close_position 后 realized_pnl 与现金对账一致。
5. 实盘冒烟:加载真实 implications.yaml(至少 1 条人工核对的关系)只读跑通。
### v2b
6. 记录器:实时跑 N tick 后 book_snapshots 行数 = N × token 数(容忍缺口);前 5 档截断正确。
7. 回测确定性:同数据同参数两次运行结果完全一致。
8. 动量(合成数据):构造单调上涨序列 → 入场触发;构造回落 → 止损触发;超时 → 时间止损;各产生正确的 realized_pnl。
9. 卖方成交:walk_book_sell 多档平均价正确、深度不足保守处理。
10. 全链路:momentum.enabled=true + 合成回放 → 回测报告产出;实时纸上循环带动量小桶跑 30s 无崩溃。

## 9. 诚实预期
- 蕴含套利:机会频率低于完整集合套利(需要两个相关市场同时错价),但单次可信度同级;主要工作量在**人工找关系**。
- 动量:先验最弱的策略。回测过不了就不上——这正是 v2b 把基础设施(数据+回测)作为主交付物的原因:即使动量被证伪,数据与回测器服务于所有未来策略。
