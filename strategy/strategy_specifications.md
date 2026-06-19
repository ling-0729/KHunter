# 选股策略说明书汇总

## 策略目录

| 序号 | 策略名称 | 策略类名 | 说明书文件 |
|:---:|---------|---------|---------|
| 1 | 仙人指路策略 | ImmortalGuidanceStrategy | [spec/仙人指路策略说明书.md](spec/仙人指路策略说明书.md) |
| 2 | 2560战法选股策略 | Strategy2560Selection | [spec/2560战法选股策略说明书.md](spec/2560战法选股策略说明书.md) |
| 3 | W底策略 | WBottomStrategy | [spec/W底策略说明书.md](spec/W底策略说明书.md) |
| 4 | 多方炮策略 | MultiPartyCannonStrategy | [spec/多方炮策略说明书.md](spec/多方炮策略说明书.md) |
| 5 | 底部趋势拐点策略 | BottomTrendInflectionStrategy | [spec/底部趋势拐点策略说明书.md](spec/底部趋势拐点策略说明书.md) |
| 6 | 涨停回马枪策略 | LimitUpPullbackStrategy | [spec/涨停回马枪策略说明书.md](spec/涨停回马枪策略说明书.md) |
| 7 | 涨停横盘策略 | LimitUpSidewaysStrategy | [spec/涨停横盘策略说明书.md](spec/涨停横盘策略说明书.md) |
| 8 | 启明星策略 | MorningStarStrategy | [spec/启明星策略说明书.md](spec/启明星策略说明书.md) |
| 9 | 多金叉共振策略 | MultiGoldenCrossStrategy | [spec/多金叉共振策略说明书.md](spec/多金叉共振策略说明书.md) |
| 10 | 阻力位突破策略 | ResistanceBreakoutStrategy | [spec/阻力位突破策略说明书.md](spec/阻力位突破策略说明书.md) |
| 11 | 强势洗盘弱转强策略 | StrongWashWeakToStrongStrategy | [spec/强势洗盘弱转强策略说明书.md](spec/强势洗盘弱转强策略说明书.md) |
| 12 | 趋势加速拐点策略 | TrendAccelerationInflectionStrategy | [spec/趋势加速拐点策略说明书.md](spec/趋势加速拐点策略说明书.md) |

## 策略分类汇总表

| 策略类型 | 策略名称 | 核心逻辑 | 适用场景 |
|---------|---------|---------|---------|
| 形态突破 | 仙人指路策略 | 冲高回落+长上影+反包 | 上升趋势中短线机会 |
| 均线突破 | 2560战法选股策略 | 股价突破MA25+均量金叉 | 趋势启动初期 |
| 形态反转 | W底策略 | 双底形态+颈线突破 | 底部反转确认 |
| K线组合 | 多方炮策略 | 两阳夹一阴 | 短线强势股 |
| 底部反转 | 底部趋势拐点策略 | 深度下跌+MACD底背离+放量反弹 | 严重超跌后的反转 |
| 涨停策略 | 涨停回马枪策略 | 涨停后回调+缩量 | 二次启动机会 |
| 涨停策略 | 涨停横盘策略 | 涨停后横盘+突破信号 | 横盘突破 |
| K线组合 | 启明星策略 | 三根K线底部反转 | 底部反转信号 |
| 指标共振 | 多金叉共振策略 | 均线+KDJ+MACD金叉共振 | 多重指标确认 |
| 阻力突破 | 阻力位突破策略 | 放量长阳突破关键阻力 | 突破买入 |
| 洗盘策略 | 强势洗盘弱转强策略 | 放量上涨+洗盘+反包 | 强势股回调 |
| 趋势加速 | 趋势加速拐点策略 | 上升趋势+放量长阳 | 趋势加速确认 |

## 通用输出格式说明

所有策略输出结果遵循统一格式：

```python
{
    'date': str,              # 选股日期（YYYY-MM-DD）
    'close': float,           # 收盘价
    'volume_ratio': float,    # 成交量比
    'reasons': list,          # 入选理由列表
    'key_date': str,          # 关键日期（信号日/突破日等）
    'key_date_type': str,     # 关键日期类型
    'pattern_details': dict,  # 形态详情（可选）
    'confirmation_details': dict,  # 确认详情（可选）
    'strategy_weight': int    # 策略权重（可选）
}
```
