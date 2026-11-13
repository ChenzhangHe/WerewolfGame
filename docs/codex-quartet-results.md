# Four-category pilot results

All six scheduled games completed and passed independent referee replay, fixed-configuration, player observation, event-delivery and tool-execution audits. There were 1,474 committed actions and zero failed model decisions. The supervisor and final offline re-audit/rating calculation exited successfully. No game replacements or fallback actions were used.

| Game | Winner | Final day | Actions |
| --- | --- | ---: | ---: |
| 01 | wolves | 5 | 277 |
| 02 | good | 4 | 230 |
| 03 | wolves | 5 | 236 |
| 04 | wolves | 5 | 226 |
| 05 | good | 3 | 199 |
| 06 | good | 5 | 306 |

Three games were won by Good and three by Wolves. All model/effort settings remained fixed for the entire game, with three seats per category in each game. Each category received 6 wolves, 6 villagers and 6 special-role seats across the pilot. Individual special roles appeared once or twice per category.

| Configuration | Elo-style rating | Approximate 95% interval |
| --- | ---: | --- |
| sol-low | 1567.40 | 1210.45–1924.36 |
| sol-medium | 1567.16 | 1210.09–1924.23 |
| terra-low | 1432.84 | 1075.77–1789.91 |
| terra-high | 1432.60 | 1075.64–1789.55 |

Ratings use the frozen hierarchical team Elo policy, starting from 1500, with one binary team outcome per audited game. The evidence consists of six outcomes, not 72 independent seat outcomes. Prior pair/trio pilot games are excluded.

Sol low and medium differ by only 0.24 points; Terra high and low also differ by 0.24 points. This pilot does not distinguish reasoning efforts reliably. Sol estimates are about 134–135 points above Terra, but every approximate 95% pairwise difference interval includes zero, so this is an exploratory signal rather than a demonstrated ranking.

[Preregistration](../artifacts/codex-quartet-v1/preregistration.json) · [Result ledger](../artifacts/codex-quartet-v1/results.json) · [Ratings and uncertainty](../artifacts/codex-quartet-v1/ratings.json)

Reproduce the offline replay and fit without model calls:

```sh
python3 scripts/play_codex_quartet.py --rate
```

## Descriptive observations

The [offline descriptive analysis](../artifacts/codex-quartet-v1/observations.json)
is produced by `python3 scripts/analyze_quartet.py`; it contains aggregate counts,
latencies and source hashes, without exporting private notes or speech content.

| Setting | Median decision seconds | Note-tool writes | Good exile votes targeting wolves |
| --- | ---: | ---: | ---: |
| Sol medium | 6.04 | 5 | 26 / 31 |
| Sol low | 6.59 | 0 | 22 / 33 |
| Terra high | 3.91 | 0 | 24 / 38 |
| Terra low | 4.38 | 0 | 28 / 32 |

Terra was faster by median response time in this sample. The timing mix includes
different roles, phases, tool calls and transport delays; it is not a controlled
latency benchmark. Both models retain their seat-local thread history independently
of optional private note writes. Vote target alignment is descriptive, not an
optimality test or an independent skill estimate: votes share the same public
information and are correlated within games. Terra low's raw vote alignment was
highest despite its lower Elo estimate, illustrating that team outcomes and vote
alignment measure different things.

Good exiled 15 wolves and 7 good players. Witch poison targeted three wolves and
one good player. In game 3, Good exiled three wolves but lost with one wolf left
after all special roles died. In game 5, Good exiled three wolves without exiling
a good player and poisoned the fourth wolf, winning on day 3.

There were zero self-explosions across 686 explosion opportunities. Those pass
choices account for about 47% of accepted actions, a potential inference-overhead
optimization for later experiments. No mid-experiment rule or prompt change is
being made. Two recovered upstream retry notifications occurred; no failed player
decision, fallback action, cross-seat history or replay mismatch was detected.
