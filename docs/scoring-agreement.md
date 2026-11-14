# 当前采用的积分与评级规则

这是项目当前采用并在测试前固定的规则，不宣称是狼人杀官方赛事标准。
积分实现已经在 Git 中：`werewolf/ratings.py`、`werewolf/league.py`、
`scripts/rate_league.py`。现在也提供 `scripts/rate_replays.py`，可仅用仓库中的
完整棋局回放复算，无需 API key、模型调用或本机私有日志。

## 两种分数分开报告

**比赛积分**：每个席位随阵营胜利记 +3，失败记 −3，没有自动 MVP 或发言奖励。
按配置汇总席位数、获胜席位数和积分。这是直观的描述性统计，不能把同一场
12 个席位当作 12 场独立比赛来解释显著性。

**Elo 尺度评级**：起点 1500，使用 `hierarchical-team-elo-v1`。它是带角色调整、
正则化的 Bradley–Terry 团队模型，不是固定 K 值的传统在线 Elo。
每场已完成且通过审计的游戏只提供一个阵营胜负结果。

## 配置与角色

Sol medium、Sol low、Terra high、Terra low 是四个独立配置。
一局中的模型、思考强度、性格和语言始终固定，席位间不共享模型线程。
不同提示词、记忆或工具设置的实验不能直接冒充同一配置的成绩。

每个配置有共享能力 `mu` 和按角色收缩的调整 `delta`。好人方取 8 个席位
能力的平均值，狼人方取 4 个席位能力的平均值：

```
D = mean(好人能力) - mean(狼人能力)
logit P(好人胜) = 好人方基准 + 布局效应 + ln(10)/400 * D
```

总评级固定按狼人 50%、村民 25%、预言家／女巫／猎人／白痴各 6.25% 加权，
避免角色安排改变时自动偏袒某个配置。共享能力的先验标准差是 200 Elo，
角色调整是 100 Elo，好人方基准是 1 logit，布局效应是 0.5 logit。
相同布局的成对游戏共享布局效应，不同批次的布局组使用不同标识。

## 失败与不确定性

未完成、宿主中断、非法动作或审计失败均保留记录，但不记作阵营败局，
也不进入能力估计。不能用默认动作补完或悄悄重开一局替换失败结果。

脚本对全部有效结果一次性重新拟合，不平均不同批次的 Elo，也不重复计数。
输出基于 MAP 和 Laplace 近似的 95% 区间及成对差值；它们不是经过校准的
排名保证。六场只是探索性样本，不能据小差异断言某种模型或思考强度更好。
完整数学说明见 [ratings.md](ratings.md)，固定策略文件见
[积分策略](../artifacts/mixed-pilot-rating-policy.json)。

## 复算最新 24 场

```sh
python3 scripts/rate_replays.py --directory replays --output artifacts/replay-ratings.json
```

结果应为：Sol low 1608.43、Sol medium 1536.47、Terra low 1462.81、
Terra high 1392.29。比赛积分分别为 +42、+18、−6、−30。

完整结果和角色胜率见 [24 场报告](codex-quartet-results-24.md)。
[首批六场报告](codex-quartet-results.md)保留为历史批次结果。

`replays/*.json` 包含所有实际发言、投票和夜间行动，能够让规则引擎逐步
重建整局并核对行动是否合法。它不包含模型请求、私人笔记或推理记录，
因此单靠公开回放不能重新审计模型当时收到了什么；原始输入隔离审计的结果
保存在各场测试报告中，原始私有档案继续留在本地。每份回放保留原始档案摘要。

## UI 加载

```sh
python3 -m werewolf --language zh
```

打开 <http://127.0.0.1:8765/>，点击“对局库”，选择任意一场，或导入
`werewolf-replay-v1` JSON。回放从开局开始；可播放、单步、拖动时间线，切换
悬疑、全知和跟随玩家视角。服务器拒绝对回放执行新的模型推理。

新对局经 `scripts/export_replays.py` 独立审计及重建确认后才能导出入库：

```sh
python3 scripts/export_replays.py path/to/completed.private.json --output replays
```
