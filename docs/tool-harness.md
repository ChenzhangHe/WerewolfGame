# Seat-scoped player tools

New DeepSeek Flash presets use `interaction_mode: "tools"`. Select `"json"`
explicitly for the original one-request adapter. The setting is frozen with each
player's configuration. Existing archives without this field restore in JSON
mode. The tool protocol version is also frozen per game and preserved on restore,
including earlier tool manifests. Tool mode currently requires DeepSeek with thinking disabled; thinking
experiments retain the JSON adapter.

## Context and permissions

Each decision starts a fresh conversation with a short trusted instruction and
compact player briefing. Full transcripts and the repository rules document are
not included in that initial message. Read tools retrieve evidence on demand.
Only that seat's prior private notes persist between decisions. Cross-game
memory remains disabled.

The runner creates every player request from the same uncommitted referee state.
`SeatToolHarness` receives a detached `game.observe(seat)`, that player's legal
options, and that player's notes. It has no engine reference, filesystem, network,
credentials, spectator view, or other player session. Its host-only `tool_context`
is retained in the private archive but excluded from every model wire request.
Filtering happens before search, pagination, and result counts. Read tools never
accept a caller-selected seat. Log offsets are local to the visible stream.

New log reads return fixed pages of at most ten events, continued with returned
offsets; models do not choose a page size. A v2 live run requested 21 entries
against a 20-entry maximum and paused. Removing that parameter in a fresh v3 game
addresses the unnecessary choice rather than silently accepting the invalid call.

Read tools cover paginated public history, public-history search, private role
results, wolf chat for Wolves only, the player's notes, and public rule sections.
Player speech stays attributed data even when it contains apparent instructions.
The compact briefing includes the role, roster, phase, available task, and bounded
recent evidence; it is not a fabricated summary of hidden state.

## Action and execution

The manifest exposes only `action_<type>` functions corresponding to the current
legal options. Legal targets and enum values are schema constrained; the host
still validates exact types, fields, speech length, and the full legal action.
Calling an action returns a proposal, not a mutation. The runner commits only
a complete valid batch through the referee, as before.

One terminal action must occur alone. Unknown tools, invalid arguments, multiple
actions, mixed read/action calls, malformed provider responses, and exhausted
budgets pause the game and retain a diagnostic trace. Tool mode never invokes
format repair, including when JSON-mode repair is enabled for the game. An
explicit retry preserves settings and cached successful decisions.

Protocol `player-tools-v4` allows at most six model requests and twelve read calls
per decision. Each request has a 24,000-character message-context limit, and the
decision has a 144,000-character cumulative message budget. The sixth request
exposes only current action tools, so the model chooses an action within the
remaining budget. No action is fabricated. Reads all use the same frozen
snapshot; repeated reads cannot produce new events. Each request retains the
player's frozen output-token cap. Exceeding a limit is a visible evaluation
failure rather than silent truncation.

Earlier v1–v3 games retain their 60,000-character cumulative budget and original
manifests on restore. A v3 live run paused on that cumulative budget after the
Witch spent five requests reading, including a repeated private-results read.
The v4 final action stage and separate context limit address that orchestration
failure in a fresh game without altering the failed game's settings.

## Transport and diagnostics

This version uses DeepSeek's native function-calling API and an in-process
capability gateway. It does not run a network MCP server or give players access
to installed computer tools. The JSON-schema manifest and local dispatch boundary
can support an MCP transport later without broadening permissions. Native tools
follow the [official DeepSeek tool-call protocol](https://api-docs.deepseek.com/guides/tool_calls/);
provider-side beta strict mode is not enabled. Nonthinking requests set
`tool_choice: "required"` so prose-only answers are not a permitted API choice.
An initial `auto`-choice live run exposed that gap and was preserved as a failed
evaluation before starting a new game with the corrected protocol.

Private inference archives contain every hop's exact credential-free wire body,
assistant action content and tool calls, tool results, usage, model identifier,
and errors. Provider reasoning is discarded. These traces are never added to a
spectator Mystery view or another player's context. Archives contain secrets
about the game and must not be given to active players.

Use `scripts/verify_live.py` to exercise a fresh configured game. Compare initial
wire size, peak and cumulative context, read calls, failures, and accepted actions
with prior JSON runs. This measures functional behavior and context reduction;
it does not establish equal strategic strength or a formal isolation proof.

## V5 critical game facts

Protocol `player-tools-v5` retains v4 budgets and final action stage.
Briefings always include concise win conditions and permanent-death consequences.
Self-explosion/pass tools explain their neutral consequences directly; other
actions and legal choices stay the same. V1–v4 games remain pinned to their
original profile. See [the explosion diagnosis](explosion-diagnostics.md).


## V6 larger context budget

Protocol `player-tools-v6` uses: 128,000 characters per request and 1,000,000
characters cumulatively per decision, including repeated request messages and
returned content. These are application character limits, not token counts or
the provider model's context window. The initial briefing, read permissions,
pagination, six-request/twelve-read limits, final action stage, output-token cap,
and v5 game facts are unchanged. No history is eagerly loaded or truncated.
V1–v5 archives retain their original budgets on ordinary restore.

A trusted local archive may be explicitly upgraded from v5 to v6 to recover a
context-budget failure: retain historical inference records and their versions;
update only the top-level `tool_prompt_version` and each pending request's
`prompt_version` to `player-tools-v6`, then validate with `Runner.from_archive`.
This deliberately changes the remaining decisions' budget and must be reported
when using that game as an evaluation. Successful cached pending actions remain
valid because v5/v6 briefings and action capabilities are identical.


## V7 read-to-action transition

Protocol `player-tools-v7` retains v6 character budgets and seat isolation.
The model may make twelve requests with at most twelve read calls. Reads close
on the twelfth request, or earlier once twelve reads have been used. That request
exposes action tools only and adds an explicit host-system ACTION PHASE notice
listing those actions. No correction retry or automatic action is introduced;
a model that still calls a revoked tool is recorded and paused.

A v6 game stopped at day 2, batch 78 because its sixth response requested public
log offset 40 after five requests spent on wolf chat, notes, and log pages 0–30.
The sixth request only offered pass/explode, so the read was correctly rejected
without execution. V7 allows more time to finish those reads and explicitly
announces the eventual transition. Ordinary restores preserve earlier profiles.
An explicitly recovered game can update its top-level and pending request
versions to v7; historical requests stay unchanged and cached successes are
retained. Such a recovery changes the remaining protocol and is not a uniform
evaluation run.


## V8 explicit output length

Protocol `player-tools-v8` retains v7 read/action budgets and information
permissions. The host instructions, initial briefing, and speech tool field
description now explicitly state the unchanged 1,200-character speech limit,
a recommended 400–700-character target, and 2,000-character notes limit. Counts
refer to decoded Unicode characters, including spaces, punctuation and newlines,
not tokens, words, or JSON escape sequences.

A v7 speech at day 3, batch 90 was rejected at 1,259 characters. Its schema
already declared maxLength=1200, but the main host instructions did not emphasize
that constraint. V8 makes it visible without optional rules retrieval. Invalid
terminal actions retain a nested `action_validation` diagnosis with the field,
actual length and maximum. The original call is preserved; no truncation,
correction retry, or fabricated action is introduced. A prompt improves guidance
but cannot guarantee that a model obeys every constraint.


## V9 authoritative public facts and faction goal

Protocol `player-tools-v9` retains v8 budgets, output limits and legal
actions. The briefing includes a seat-local faction goal and `public_state`:
living and eliminated seats, confirmed public ability reveals, unconfirmed dead
roles, the actor's published ballots, and whether today's dawn has been announced.
These fields derive only from already-visible roster state and public events,
never speech claims, private notes, unrevealed roles or unsubmitted ballots.
Wolves also receive the intersection of their existing known roster and living
seats. No new information capability or model-selected action is introduced.

The instructions clarify rules and evidence boundaries exposed by the completed
[2026-11-08 game audit](game-audit-2026-11-08.md), including no Guard, living
revealed Idiot, potion visibility, private Seer results, and continued allegiance
after elimination. V1–v8 archives remain pinned on normal restore. Regression
tests cover hidden-state noninterference and unchanged action schemas; this is
not evidence that a model will never misreason or betray its team again.


## V10 self-claims versus Idiot ability activation

Protocol `player-tools-v10` retains v9 budgets and legal actions.
`public_state` adds `idiot_protection_activated_seats` (public ability reveals) and
`ordinary_exile_voters` (living seats before runoff exclusions, excluding only
formally revealed Idiots). A self-claim never changes these lists. Current action
tools remain authoritative for runoff and other task-specific eligibility.
The instructions explicitly distinguish claiming Idiot from its triggered
protection, and reiterate that a living Idiot is not a dead special role.
V1–v9 restore profiles are unchanged. See the fixed-v9 rerun in the game audit
for the exact evidence and the limits of that validation.


## Native thinking transport

Thinking is an explicit frozen player setting, supported with native tools.
Provider reasoning text is retained only in the current `_tools_live` call's
local message list and passed back to that same seat/decision. No cross-seat,
subsequent-decision, replay, viewer, or archive copy receives it. Empty provider
reasoning is carried as an empty string. Actual reasoning counts toward context
and cumulative budgets. Numeric `reasoning_tokens` usage is retained.

Thinking trace `wire_request` bodies redact only `reasoning_content`; hashes,
raw/JSON character lengths, message indices and actual request character totals
record continuity without exposing the text. The auditor verifies all visible
wire fields and passback metadata against preceding assistant states in that
same attempt. It cannot reconstruct or semantically inspect redacted reasoning.
Synthetic tests inspect actual outbound payloads for isolation and full passback.
Non-thinking archives preserve their original exact-wire representation.


## V11 decision support and thinking-compatible invocation

New games use `player-tools-v11`. The same native protocol uses `tool_choice:
auto` in both off/high modes: a live synthetic check established that DeepSeek
rejects `required` with thinking enabled (HTTP 400). The application still accepts
only one legal terminal native call; prose is never converted into an action or
silently repaired. The final action-only stage also uses the compatible choice.

The briefing now includes core public rules and the actor's prior notes, labeled
as beliefs. Its bound is 24,000 characters, while individual read outputs remain
12,000. No public history is eagerly loaded; large recent events remain whole
entries or explicitly omitted with continuation pointers. V11 has a 384,000
character request cap and 5,000,000 cumulative character budget, including
reasoning passback, with twelve model requests/twelve read calls. V6–v10 retain
128,000/1,000,000 budgets and all earlier profiles retain their manifests.

The old explosion task is presented as a routine `daytime_continuation` check.
It encourages maintaining a private plan and reconsidering on new evidence,
without removing any legal action or window. Pass/explode are both model choices.
There is no hard self-explosion rate limit or automatic pass.

Two pure read tools support arithmetic:

- `calculate_exile_votes`: user-proposed ordinary ballots, public Sheriff weight,
  tied leaders, and unspecified voters. It never queries pending votes; runoff
  exclusions are explicitly outside this calculation.
- `check_win_hypothesis`: a complete user-supplied role assignment and proposed
  additional deaths. Checks public lineup counts and the actor's already-known
  facts, then computes remaining factions. All unverified assignments remain
  labeled hypotheses, not referee confirmations. It does not simulate night
  abilities, priorities, or future player behavior.

Both tools consume only detached seat observations and caller arguments. Tests
cover a living Idiot blocking a false all-specials-dead win, self-claims versus
formal reveals, duplicate/ineligible votes, Sheriff weight, own wolf roster
conflicts, and independence from other unrevealed assignments.
