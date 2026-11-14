# Sol vs. Terra: scoring continuity

The current schedule fixes Sol at medium effort and Terra at low. Scoring has only two entries, **Sol** and **Terra**. The grouping was explicitly changed after the historical outcomes were observed; it is a retrospective model-family analysis, not the originally preregistered four-setting analysis.

All 35 completed historical games are retained, including the original 30. Historical Sol low/medium seats map to Sol; Terra high/low map to Terra. The one upstream-failed attempt remains excluded. New games append outcomes to the same two-entry fit. No game is counted twice, and old Elo scores are not averaged. The rating formula and priors are unchanged; only the entry grouping changes.

| Model | Pooled Elo-style rating before new batch | Approx. 95% interval |
| --- | ---: | --- |
| Sol | 1602.60 | 1295.18–1910.01 |
| Terra | 1397.40 | 1089.99–1704.82 |

Historical effort exposure is disclosed in the JSON output: each family has 105 low-effort and 105 medium/high-effort seat appearances. These scores pool different historical efforts and therefore do not isolate a model effect at equal effort. The original configuration-level scores remain available as a separate historical report.

```sh
python3 scripts/rate_replays.py --grouping model-family --output artifacts/model-family-ratings.json
```

The six fresh games use seed 26000, six seats per model per game, fresh threads and no cross-game memory. All six launch in parallel after re-auditing the completed Sol medium/Terra low baseline. Frozen hashes of the 35 historical replay files prevent accidental changes or duplicate additions during the batch. The batch writes `ratings.json` for history plus new outcomes, and `batch-ratings.json` for the new games alone; both have only Sol/Terra entries. The old failed attempt is reported separately in historical reliability metadata.

```sh
python3 scripts/play_codex_league.py --rate --plan artifacts/codex-sol-terra-26000/plan.private.json
```

[Historical four-setting results](codex-quartet-results-35.md) · [Model-family ratings](../artifacts/model-family-ratings.json) · [Current batch preregistration](../artifacts/codex-sol-terra-26000/preregistration.json)

## Subsequent host interruption and continued collection

The seed-26000 batch completed four games. Two remaining partial games stopped
when their supervisor and worker exited; neither recorded a model-decision error.
Their referee checkpoints replay correctly but lack all pending responses, so
they are retained as host interruptions, never assigned invented outcomes.
This produces **39 valid games from 42 attempts**, preserving every prior valid
outcome. The earlier table is the 35-game historical starting point; current
pooled values are in `artifacts/model-family-ratings.json` and live campaign data.

The next twelve games (27000/28000) are independent additional games, six at a
time. Every new outcome is appended once to the pooled Sol/Terra fit. Old model
reasoning, private notes and observations are never delivered to new actors.
