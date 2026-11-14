# Historical four-setting comparison: 35 valid games

36 attempts returned 35 completed, audited games and one retained upstream failure. The valid games contain 8485 actions. This is the historical configuration-level view; the current scoring groups models into Sol and Terra, reusing these same 35 outcomes.

| Historical setting | Elo-style rating | Approx. 95% interval | Seat wins |
| --- | ---: | --- | --- |
| sol-low | 1627.18 | 1347.24–1907.13 | 65/105 (61.9%) |
| sol-medium | 1544.16 | 1263.90–1824.41 | 59/105 (56.2%) |
| terra-low | 1455.02 | 1174.77–1735.27 | 53/105 (50.5%) |
| terra-high | 1373.64 | 1093.70–1653.58 | 47/105 (44.8%) |

The excluded attempt is `codex-quartet-23000-03`: Terra low, seat 12, received a non-retryable upstream error after 0.67 seconds, with no tool calls or reported usage. Its saved referee state replays correctly. The sanitized code is `other`; the exact service cause and any relation to six-way concurrency are unknown. It is not scored as a model defeat.

All pairwise approximate 95% rating-difference intervals include zero. These Laplace intervals do not establish a reliable ranking or that thinking effort has no effect.

## Historical role wins

| Role | Sol low | Sol medium | Terra low | Terra high |
| --- | --- | --- | --- | --- |
| wolf | 18/34 (52.9%) | 16/36 (44.4%) | 12/34 (35.3%) | 10/36 (27.8%) |
| villager | 26/36 (72.2%) | 22/34 (64.7%) | 20/36 (55.6%) | 16/34 (47.1%) |
| seer | 4/9 (44.4%) | 6/10 (60.0%) | 4/8 (50.0%) | 7/8 (87.5%) |
| witch | 4/8 (50.0%) | 4/8 (50.0%) | 7/9 (77.8%) | 6/10 (60.0%) |
| hunter | 5/10 (50.0%) | 7/9 (77.8%) | 5/8 (62.5%) | 4/8 (50.0%) |
| idiot | 8/8 (100.0%) | 4/8 (50.0%) | 5/10 (50.0%) | 4/9 (44.4%) |

Role wins mean the faction won, not that a skill use or vote was correct. Same-game seat outcomes are correlated.

```sh
python3 scripts/rate_replays.py --grouping configuration --output artifacts/replay-ratings.json
```

[Current Sol/Terra grouping](sol-terra-scoring.md) · [Four-setting fit](../artifacts/codex-quartet-23000/cumulative-ratings.json) · [Failure evidence](../artifacts/codex-quartet-23000/failure-diagnostics.json) · [All complete replays](../replays/)
