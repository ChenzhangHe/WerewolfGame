# Native validation feedback and explicit confirmation (v14)

The v13 validation game completed, but the next season exposed a remaining
provider contract violation. With `strict: true`, DeepSeek returned
`action_pass({"parameters": {}})` for a schema with no properties and
`additionalProperties: false`. The client rejected it correctly. Strict
server-side decoding alone was insufficient. An empty-object decoder corner
case is a plausible explanation; its provider-internal cause is not established.

The season circuit breaker stopped after two in-flight games, leaving ten
unattempted. The second game exhausted three transport attempts (incomplete
streams and an idle timeout). Its old trace lacks stream completion-state
metadata, so we cannot retrospectively tell exactly where those streams ended.
Those v2 records remain unchanged and are excluded from the new season.

## Explicit wire contract

`player-tools-v14` retains seat-scoped tools and strict schemas, and gives every
otherwise fieldless function a required `confirm: true` argument. This avoids
an empty object at the decoder boundary. Confirmation acknowledges a tool
invocation; it does not claim a referee result. The host checks exactly that
field and value, then maps the declared wire invocation to the existing game
operation. It never unwraps guessed `parameters` objects or invents a choice.

## Ordinary tool rejection feedback

Every native response executes against a draft of the seat capability. A valid
read/notes transaction can update that draft. A terminal action can occur alone
or with one private note in either native array order. Only an entirely valid
transaction is accepted. An invalid action, malformed arguments, unknown tool,
or mixed terminal/read response yields typed tool errors for the original call
IDs. All effects of that transaction, including its note write, are rolled back.
Previously valid staged notes from earlier hops remain available.

The model receives the actual tool errors inside its **same** decision context
and may submit new native calls. The host does not rewrite its answer, select a
default action, launch a fresh conversation, or feed it another seat's data.
Raw rejected calls, rollback results, error codes and subsequent calls remain
in the private trace. The auditor reconstructs both rejections and successes.

At most two rejected transactions can be corrected, inside the original twelve
model-request/utility budgets. A third rejection stops the game. Public-text
validation and exact legal-option validation remain mandatory. The legacy
`allow_format_repair` switch controls the old JSON adapter, not this native
function error-response protocol. Recovered rejections are reported separately
from final failed decisions and strategic outcomes.

## Streaming and transport

- v14 accepts an explicit terminal `finish_reason` followed by EOF even when the
  redundant `[DONE]` delimiter is lost. The native envelope and complete action
  arguments still must validate before any game action is accepted. EOF before
  a finish reason is rejected; truncated/length-limited output cannot submit.
  v13's historical reader behavior remains the default for its archived profile.
- Incomplete-stream diagnostics now retain only byte/chunk/tool counts and the
  terminal reason, with no text or reasoning. Unexpected non-SSE data is reported
  explicitly instead of being ignored until a generic EOF.
- Up to six logged transport attempts use bounded exponential backoff and
  Retry-After. Authentication/schema errors do not retry. Each hop has a
  900-second budget and 90-second socket idle bound; v14 also has a 1200-second
  whole-decision budget checked between hops/frames. A pending socket read may
  extend a wall budget by at most the idle bound. Failed-request usage can be
  unknown, and no API availability guarantee is implied.

Both fresh real-model probes passed: a normal confirmed action and a deliberate
out-of-range log request followed by the model reading its error and submitting
a legal confirmed action in the same context. Synthetic tests reproduce the
observed wrapper error, rollback paired private notes, bound feedback, reject
public-field spill/multiple actions, and detect tampered tool results.

## Frozen v3 season

v3 uses a distinct DeepSeek configuration ID and a new role-balanced plan.
The first preregistered game is a serial gate **and counts as game one of the
twelve**. Resume the remaining eleven only after that game completes and audits.
Old partial games and the separate v13 validation game are not included.

```sh
python scripts/play_league.py --create-plan
python scripts/play_league.py --run --parallel-games 1 --max-new-games 1
python scripts/play_league.py --run --parallel-games 2
python scripts/rate_league.py
```

New files live under `artifacts/mixed-v3`. Settings stay fixed throughout each
game and season. Execution requires the frozen source fingerprint; historical
plans remain available for offline auditing. A failed result stops new game
launches while the host collects already-running evidence.

## First rated gate result

`pilot-14000-01` completed with a Good victory on day 3: **190 committed actions
in 85 batches**, taking 46.2 minutes. Independent referee replay and both
provider input/tool audits passed. Three rejected native transactions were
corrected by the model within its decision context; two HTTP retries recovered.
There were zero final failed decisions. This game is the first rated outcome
of v3, and the remaining eleven continue with the identical frozen settings.

[Audited gate summary](../artifacts/mixed-v3/pilot-14000-01.json).
