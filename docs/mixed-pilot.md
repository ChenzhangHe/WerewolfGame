# Twelve-game mixed-provider pilot

This is an exploratory comparison of two complete AI player configurations,
not a model-only benchmark or a stable Elo ranking. Configuration and prompts
stay fixed throughout the season. The game rules remain [rules v1](rules-v1.md).

- `sol-high-codex`: `gpt-6.1-sol`, high effort, native Codex app-server using
  the existing ChatGPT subscription. One isolated thread per game/seat persists
  for the game. Authorized event increments are injected without idle inference.
- `deepseek-flash-high-tools`: `deepseek-flash`, thinking enabled, high effort,
  temperature null, output budget 32768, native v12 tools. Each decision starts
  with its own briefing and committed notes; history is read through seat tools.
- All games use Chinese and the existing fixed seat personalities. Each game
  has six seats from each entry. Models do not receive opponent provider IDs,
  schedule, scoring metadata, other-seat notes, or the full referee state.

## Schedule fixed before inference

Six independent role layouts each have two complementary entry assignments.
Both games start at the opening with fresh threads; no earlier transcript is
replayed. Each layout contains four Wolves, four Villagers, Seer, Witch, Hunter,
and Idiot. Every entry plays 72 seats: 24 Wolves, 24 Villagers, and six of each
special role. Seats and personalities are balanced through complementary
assignments as well. Sol's Wolf count ranges from zero to four across games,
so the faction compositions change instead of making entry effects identical
in every game. Paired games share a layout but have different event-order seeds.

The private preregistration contains exact roles, assignments, configurations,
execution limits, and a source fingerprint. Code changes cause the run to stop
rather than silently combine protocols. Raw evidence is private and ignored by
Git; aggregate reports can be committed. Do not give the plan or raw archives to
player models.

## Scores and failure policy

Each participating seat receives **+3 for its team's victory, −3 for defeat**,
including dead seats. This borrows the outcome points from the
[official 2026 faction league](https://langrensha.com/20260413/31014_1295775.html).
We do not adopt its full competition scoring system. No automatic MVP or
behavior bonus influences the main score; voting, poison, exile, and explosion
metrics are separate diagnostics. The game objective supplied to players stays
team victory.

We report counts and role-specific results, plus a fixed weighted win rate:
Wolves 50%, Villagers 25%, each special role 6.25%. Its point equivalent is
`6 × weighted_win_rate − 3`. This prevents eight Good seats versus four Wolves
from setting the relative faction weight. Missing role data leaves this metric
unavailable. Interim numbers are provisional until all scheduled games finish.

A failed or interrupted attempt is retained, receives no strategic points, and
is listed separately as a reliability failure. It is never replaced, repaired,
given default actions, or resumed by recreating a seat's thread. Only completed,
audited games enter strategic scores; the valid/attempted denominators always
remain visible. This can introduce selection bias if failures are not random.

Seats in one game share its outcome, and paired games share their initial
layout. Twelve games are an engineering/behavior pilot, not 144 independent
skill trials. The tournament score board does not fit an Elo rating. A separate
[exploratory role-aware Elo-scale fitter](ratings.md) is available; its estimates
include uncertainty and must not be treated as stable rankings from this pilot.

## Run and audit

Load `DEEPSEEK_API_KEY` from the ignored repository `.env` (see
[provider setup](provider-setup.md)) and sign Codex CLI into ChatGPT. Never
extract or copy a subscription token into this application's environment.

```sh
python scripts/play_league.py --create-plan
python scripts/play_league.py --run --parallel-games 3
python scripts/play_league.py --audit artifacts/pilot-12000-01.private.json
```

The runner uses up to three games and four decisions per game concurrently.
All paid responses in a decision batch are collected before the referee commits
any of them. Run `--run` again only to schedule still-unattempted games;
completed games are audited again and failed/interrupted games are retained.

`artifacts/mixed-pilot-results.json` contains results and the tentative score
board. Per-game summaries include separate provider usage and diagnostics.
`*.progress.json` files show the last committed phase, not whether a currently
pending model request is hung. Raw `*.private.json` files record exact scoped
inputs and tools without raw hidden reasoning. Independent replay checks every
observation against referee state, each legal action against the pending batch,
Codex event deliveries against the seat history, and every DeepSeek wire body
and tool result against its fresh seat capability. Isolation tests deliberately
inject foreign notes and wire messages and require rejection.
