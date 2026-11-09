# DeepSeek Flash live validation — 2026-11-08

Real DeepSeek API calls were exercised against the local spectator server with
twelve AI seats. Player settings stayed fixed within each game. The test archives
are local `*.private.json` files and are deliberately excluded from Git.

## Observed results

| Configuration | Outcome | Recorded requests |
| --- | --- | --- |
| Thinking enabled, low effort, 4096 tokens | Recovered the original action-format failure, completed day 1, then paused during day 2 speech after exhausting the response budget | 160 |
| Thinking enabled, low effort, 8192 tokens | Reached day 2 Sheriff election, then paused after exhausting the response budget | 57 |
| Thinking disabled, temperature 0.7, 8192 tokens | Completed three day/night rounds; paused at night 4 after 98 committed batches | 265 |

The fast dialogue run had **265 accepted responses, zero failed attempts, and
zero format-repair attempts**. It included 50 Chinese speech/discussion/last-word
responses. Covered decision types included wolf discussion and attack, Witch,
Seer, nominations, campaign speeches, withdrawals, Sheriff votes, speaking
direction, ordinary speeches, exile votes, last words, badge transfer, and Wolf
explosion opportunities. Hunter shots and Idiot reveal were not triggered in
this run; those branches have engine test coverage.

The fast run stopped at the requested three-round boundary, before any night-4
actions. It did not reach an overall game winner. Different seeds and protocol
versions were used while diagnosing failures; this is a functional reliability
check, not a controlled comparison of model strength or win rates.

## Failure diagnosis and changes

- The original failure occurred when transitioning from wolf discussion to an
  attack decision. Its rejected payload was discarded by the old adapter, so
  its exact invalid field cannot be recovered from that log.
- Later live testing captured `{"type":"json_object"}` as a proposed game action.
  That is a serialization format name, not a legal action. Task-specific JSON
  instructions now distinguish these and remove the unconditional speech example.
- Rejected action content and safe model/usage metadata are now retained
  privately. One bounded format-repair request uses only the same player's
  unchanged observation, legal options, and rejected output. No illegal response
  is coerced into an action or partially committed.
- Two 4096-token voting failures completed after one explicit retry with the
  same settings and cached successful votes. A later speech hit the same budget;
  the separate 8192-token thinking run also exhausted its budget. Existing games
  were preserved rather than changing their settings mid-play.
- New viewing games default to fast dialogue mode. Thinking remains available
  before game creation for separate evaluation runs.
- Up to four independent requests run concurrently, with a frozen pre-batch
  view and deterministic recording order. A failed request preserves other
  successful paid responses for retry.

## Checks on the successful live archive

- All 265 requests used DeepSeek Flash, thinking disabled, and an 8192-token cap.
- Every request identified only its own player; no assignment seed or global
  decision IDs appeared in the player input.
- Other seats' role fields were absent unless publicly revealed. Wolf-only,
  Seer-only, and Witch-only events appeared only in their permitted observations.
- Each request's private notes matched that seat's previous accepted notes.
- All 50 accepted speech responses contained Chinese text.
- The actual credential was absent from the archive; no tools were supplied.
- Reconstructing the full game from the archive invoked no model and preserved
  the night-4 state. Initial Mystery replay still concealed every assigned role.

These structural checks complement paired hidden-state tests; they are not a
claim of a formal proof that all future additions preserve information isolation.

One large archive download ended early after the three rounds had completed.
The complete archive was recovered, and the verifier now streams downloads,
checks their declared length, retries transfer once, and replaces a previous
archive only after successful JSON validation. Download retries never advance
the game or invoke a model.

Validation at completion: **90 automated tests pass**, JavaScript syntax check
passes, and all three private archives are retained locally. The successful
server game is restored and paused at night 4 for spectator replay or continuation.

## Native tool-harness validation

The tool-harness series uses fresh Chinese games with twelve real DeepSeek Flash
players, thinking disabled, temperature 0.7, and 8192 output tokens. Every failed
run remains in a separate local private archive; none is relabeled as a success.

| Protocol | Result |
| --- | --- |
| v1, automatic tool choice | Four accepted actions, three cached uncommitted actions, one failed attempt. A Wolf read chat then returned prose without a terminal call. |
| v2, required tool choice | 77 accepted actions in 27 batches, then one invalid read on day 3: Hunter requested `limit: 21` against the declared maximum of 20. |
| v3, fixed ten-entry pages | 80 accepted actions in 26 batches, then one cumulative-message-budget failure on day 3. Witch used five reading requests, including a repeated private-results read. |

A separate configuration-check run was interrupted after nine accepted actions
because it still used automatic tool choice; it is excluded from required-tool
results. The rejected v1 prose was never converted to an attack, the v2 oversized
page was never silently clamped, and the v3 budget was never enlarged midgame.

The corresponding fixes require tool calls at the API level, remove caller
control of page size, and reserve the final request for action tools. Protocol v4
separately bounds each request's message context to 24,000 characters and all
messages sent during a decision to 144,000 characters, with six model requests
and twelve read calls maximum. Old games retain their original protocol.

Initial wire bodies in v2 and v3 were about 61–62% smaller than the equivalent
JSON adapter built from the same authorized observations. Cumulative wire
traffic was respectively 44% and 63% larger because tool interactions repeated
context across requests. These are character counts including tool schemas,
not a token-cost or strategic-strength comparison. Smaller initial prompts do
not by themselves mean lower total inference usage.

Run the local audit without sending an archive to a model:

```sh
python3 scripts/audit_tools.py artifacts/deepseek-tools-v4-zh.private.json
```

The audit reconstructs each player's permitted historical observation and notes,
checks exact credential-free wire bodies and continuation messages, executes
reads again against only the frozen seat view, and binds every recorded result
to the actual model call. It also validates checkpoint replay without inference.

### Completed v4 run

The fresh v4 game completed three rounds and stopped before night-4 actions:
**88 accepted actions in 33 batches, zero failed attempts, zero format repairs**.
It made 286 model requests and 299 successful read calls. Two decisions reached
the sixth, action-only stage and completed successfully. All sixteen accepted
speech/discussion responses contained Chinese text. The run had no overall game
winner at the requested boundary.

Mean initial wire size was 7,996 characters versus 19,665 for the equivalent JSON
adapter: **59.3% smaller**. Peak whole-wire size was 22,129 characters, including
tool schemas. Peak message context was 19,295 characters, below the 24,000 limit.
Mean cumulative wire traffic per action was 36,938 characters: **87.8% larger**
than the equivalent one-call JSON request. This implementation bounds and reduces
initial context; further work is needed to reduce repeated tool-call traffic.

The full local audit passed, including own-seat historical observations and
notes, all exact requests and tool results, legal terminal actions, and replay.
The actual API credential was absent from the archive. Restoring the archive
made no inference calls and preserved the night-4 state and hidden-role
projections. The game is restored and paused at `http://127.0.0.1:8765/`; the prior
JSON game remains preserved in its original private archive.

Validation after this series: **146 automated tests pass**, JavaScript syntax
check passes, and all diagnostic archives remain local and excluded from Git.
Hunter shots, poison actions, Idiot reveals, and an endgame were not exercised
by the completed v4 run; their referee branches retain automated coverage.
