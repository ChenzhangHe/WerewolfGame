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
