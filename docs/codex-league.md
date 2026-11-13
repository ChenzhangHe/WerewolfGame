# Codex configuration league

The initial pilot runs six new 12-player games comparing **GPT-6.1 Sol / medium**
and **GPT-6.1 Terra / low**, with six seats for each configuration in every game.
Both use the same subscription-backed Codex app-server harness, prompts, tool
catalog, 600-second turn deadline, and two inference workers per game. Model,
effort, language, name and personality are fixed before play. The pilot uses
Chinese; existing English support is unchanged.

Three role layouts are played twice, with complementary configuration assignments.
Each configuration receives 12 wolves, 12 villagers, and 3 of each special role,
and occupies each numbered seat/personality three times. Faction composition
varies from zero to four Sol wolves, rather than giving both models the same
faction mixture in every game. Configurations and the role layout are private
host metadata. A player receives only its authorized observation, legal options,
private notes and seat-local event stream. It gets one fresh thread per game;
canary data, other games and ratings never enter that thread.

The seven requested configurations have passed two synthetic decisions each,
including private tool reads, note writes and same-thread reuse. These are
capability checks, not rated games. The other five configurations remain available
for a later comparison: Sol high/low, Terra high, and Luna high/medium.

## Reproduce the initial pilot

Sign in using `codex login`. No OpenAI API key or DeepSeek key is needed.
Create two synthetic canaries in a fresh output directory:

```sh
python3 scripts/verify_codex.py --synthetic --seats 1 --decisions 2 --exercise-tools --model gpt-6.1-sol --effort medium --output artifacts/codex-sol-medium-terra-low-v1/canary-sol-medium.private.json --summary artifacts/codex-sol-medium-terra-low-v1/canary-sol-medium.json
python3 scripts/verify_codex.py --synthetic --seats 1 --decisions 2 --exercise-tools --model gpt-6.1-terra --effort low --output artifacts/codex-sol-medium-terra-low-v1/canary-terra-low.private.json --summary artifacts/codex-sol-medium-terra-low-v1/canary-terra-low.json
python3 scripts/play_codex_league.py --create-plan
python3 scripts/launch_codex_league.py
```

Use a fresh directory and seed for another pilot; do not overwrite existing paid
evidence. `--plan` selects a different plan location. The plan freezes source
fingerprints, exact roles/configurations, canary hashes, execution settings and
the existing hierarchical team Elo policy. The public preregistration exposes
settings and exposure totals without revealing scheduled roles.

The launcher owns a detached process session and redirects stdout/stderr to
`verification.log`. It creates exclusive ownership metadata and the runner holds
an OS lock, preventing duplicate launches. Closing a chat or terminal does not
own the game's lifecycle. Status is saved in `verification-status.private.json`;
individual `*.progress.json` files show live phase, committed actions or response
waits. Logs, raw evidence and private plans are ignored by Git. This CLI league
is separate from the spectator server at port 8765.

Game 1 is the full-game gate and counts toward the six. Only after its completed
referee replay and seat-information audit pass do the remaining games run, with
at most two games concurrently. A failed game stops new launches while collecting
in-flight games. Failed or uncertain attempts are retained and excluded from
ratings; no default action, replacement game, or recreated thread is substituted.
Resume between completed games is supported by the direct runner command, but a
retained failure blocks further execution pending investigation.

`results.json` and `ratings.json` update after each returned game. Ratings use one
team result per completed audited game, fixed priors and approximate uncertainty,
using the same formula as the earlier pilot. Six games are exploratory and cannot
establish a reliable model ranking. Failures are reported separately from skill.
To independently re-audit saved completed games and refit without model calls:

```sh
python3 scripts/play_codex_league.py --rate
```

A future seven-entry experiment can use `--profile seven` with a fresh directory
containing canaries for all seven configurations. Fourteen games provide exact
role and position balance; six provide only approximate balance. Neither profile
is started by the initial pair pilot.

## Three-model pilot

The separate `codex-trio-v1` pilot compares **Sol / medium**, **Terra / low** and
**Luna / medium** in six new games, with four seats per configuration per game.
Two three-game rotation blocks give each entry 8 wolves, 8 villagers, and 2 of
each special role. Every configuration occupies each seat/personality twice.
Wolf composition varies across games. Efforts differ deliberately, so the result
compares these configurations, rather than isolating model identity at equal effort.

The previously passed synthetic canaries for these exact configurations are
re-audited and their hashes frozen. No previous game data or canary observations
are supplied to the new game players. The pair pilot keeps its existing plan,
source fingerprint, results and in-flight games.

After placing those three canary files in the new directory:

```sh
python3 scripts/play_codex_trio.py --create-plan
python3 scripts/launch_codex_league.py --runner trio --plan artifacts/codex-trio-v1/plan.private.json
python3 scripts/play_codex_trio.py --rate
```

Use the same synthetic-canary command above with `gpt-6-luna`, effort `medium`,
and the corresponding `canary-luna-medium` filenames to validate Luna. Each pilot
has its own logs, progress, result ledger, ratings, ownership marker and OS lock.
Each runs its first game as an audit gate, then at most two games concurrently.
Six outcomes provide only preliminary ratings with substantial uncertainty.

## Four-category pilot

The separate `codex-quartet-v1` pilot uses six fresh 12-player games with three
seats in each category: **Sol / medium**, **Sol / low**, **Terra / high**, and
**Terra / low**. Each is an independent rating entry. The same prompts, seat
tools, thread isolation, execution limits and rating policy apply to all four.

Three complementary assignment pairs give each category 18 seats: 6 wolves,
6 villagers and 6 special roles. Each individual special role appears once or
twice per category; six appearances of a role cannot divide equally among four
categories. Every possible two-category Wolf coalition occurs once, providing
variation for the rating fit. Category, model, effort and personality remain
fixed for each seat throughout a game. Earlier pilot outcomes remain separate.

The exact four synthetic capability checks are re-audited before execution and
frozen by hash. After placing their raw canary files in the fresh directory:

```sh
python3 scripts/play_codex_quartet.py --create-plan
python3 scripts/launch_codex_league.py --runner quartet --plan artifacts/codex-quartet-v1/plan.private.json
python3 scripts/play_codex_quartet.py --rate
```

The first game must complete and pass all audits before the remaining games
start, with at most two quartet games in parallel. Failed attempts remain visible
and unscored; new launches stop on a failure. Logs, progress, results and ratings
live under `artifacts/codex-quartet-v1`. Six completed outcomes will provide only
preliminary ratings, with uncertainty shown explicitly.

## Twelve-game extension

The separately frozen continuation adds 12 fresh games to the completed six-game
four-category pilot. Model, effort, prompt, tools, language, harness limits and
rating policy are unchanged. Two fresh six-game cohorts use seeds 19000 and 20000,
with category-label rotations of one and two positions. This reduces the original
special-role exposure imbalance. Across all 18 planned games, each category has
18 wolves, 18 villagers, and 4 or 5 appearances in each special role.

```sh
python3 scripts/extend_codex_quartet.py --create-plan
python3 scripts/launch_codex_league.py --runner extension --plan artifacts/codex-quartet-extension-v1/plan.private.json
python3 scripts/extend_codex_quartet.py --rate
```

The completed baseline is re-audited and its plan, result ledger and six private
archive hashes are frozen. The 12 new games receive fresh threads and no previous
game information. They run behind one new full-game gate and then at most two at
a time, stopping new launches on failure. Outputs in the extension directory are
`ratings.json` for new games alone and `cumulative-ratings.json` for the combined
18-game schedule. Cumulative ratings refit each valid outcome once with unchanged
priors; they do not average cohort ratings. Layout group IDs are namespaced by
cohort so different role layouts cannot accidentally share an intercept.
