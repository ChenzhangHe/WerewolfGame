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

New games use `player-tools-v6`: 128,000 characters per request and 1,000,000
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
