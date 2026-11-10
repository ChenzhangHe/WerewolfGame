# Player providers and bilingual games

The default `demo` provider is a deterministic scripted smoke-test player. It
does not call an AI model and must not be used as evidence of AI capability.
Real inference uses one of the adapters below. Adapters have mocked HTTP coverage.
DeepSeek Flash has also passed a real connection check with a locally supplied
key. OpenAI API and subscription transports remain unverified with live accounts.

## Configuration and language

Configure all twelve seats before starting the game. `provider`, `model`,
`personality`, `temperature`, `max_tokens`, `thinking`, `reasoning_effort`, and `interaction_mode` are frozen for that game. Game
language is `en` (English) or `zh` (Simplified Chinese), and is copied into every
seat's frozen configuration. Referee announcements and player speech use that
language. Changing the interface language does not translate old speech or alter
an active game. Generated text is instructed to use the game language; model
language compliance still needs evaluation with actual models.

Each decision starts a fresh context. `interaction_mode: "tools"` uses a compact
briefing and seat-scoped read/action tools; `"json"` sends the permitted observation
and legal options in one request. The DeepSeek Flash preset selects tools. Old
archives and explicit configurations without the field retain JSON mode.
Other seats' private notes, referee archives, assignment seed, global decision
IDs, credentials, and provider session continuations are never supplied. Every
simultaneous batch uses one frozen pre-commit view. See [the tool harness](tool-harness.md).

Secrets are read from the server process environment or the local, git-ignored
project `.env` file. The `.env` loader supports literal `DEEPSEEK_API_KEY` values
only, does not execute shell expressions, and preserves existing process values.
Restart after changing an already loaded key. Do not put credentials
in player configuration JSON, URLs, personalities, source files, or commits.
Credential presence is checked when creating a game. Presence does not establish
validity, account entitlement, or model availability; successful inference is the
real access check. No automatic provider, model, or billing-path fallback occurs.

## DeepSeek API

Set `DEEPSEEK_API_KEY` in the terminal that starts the server or in `.env` at the
repository root, using the committed `.env.example` as a template. Select
`provider: "deepseek"` and model `deepseek-flash`. The
adapter calls `https://api.deepseek.com/chat/completions`. Tool mode uses native
function calls; JSON mode enables JSON output.
It passes the configured temperature and token budget when they are not null.
Incomplete, invalid, or illegal responses pause the game with private diagnostic
traces. No substitute action is created. Both JSON and native tool modes support
explicit thinking settings. For tools plus high thinking, use temperature null
and a 32768-token output budget; output tokens include provider reasoning.

Use `python3 -m werewolf --check-deepseek --language en` for one explicit live
speech request using synthetic public information. The UI's **Test connection**
does the same without sending the active game's state. Neither check runs
automatically, and both consume API usage. Check success verifies access to the
requested model for that request, not a guarantee of future availability.

The `deepseek_flash` game preset and the UI's twelve-seat Flash button use
`thinking: "disabled"`, `reasoning_effort: null`, `temperature: 0.7`, and
`max_tokens: 8192`. This fast dialogue preset keeps real AI decisions while
avoiding the long reasoning delays observed in live tests. Thinking-enabled
4096 and 8192 configurations both exhausted their budgets before producing final
action content. Two 4096-token voting requests succeeded after explicit retries
with unchanged settings; a later speech still hit that limit. Thinking remains
available per player for separate evaluation series. Preset changes apply only
to new games; never relabel fast-mode results as thinking-mode results.
Thinking-enabled configurations reject non-null temperature
because the provider would ignore it. Disabled thinking omits effort and permits
temperature. Existing unspecified thinking settings explicitly send `disabled`
instead of inheriting DeepSeek's provider-side enabled/high default. All fields
are part of the frozen configuration snapshot and credential-free wire archive.

The public model ID `deepseek-flash` is documented as served by
DeepSeek-V4.1-Flash-1017 as of 2026-11-08. Provider-side aliases can change; preserve
the returned model identifier alongside the requested model. See
[thinking controls](https://api-docs.deepseek.com/guides/thinking_mode/). Tool
conversations are local to one seat and decision. Provider `reasoning_content`
is never shown or archived. In thinking tool mode it is passed back only inside
the same seat/decision in-memory conversation, as required by DeepSeek; it is
discarded when that decision ends. The archive retains only hashes, character
lengths, and numeric usage for these states. All other wire fields, action
content and tool transcripts remain private archive material. The setup UI no
longer switches tools to JSON when thinking is enabled, and supports 32768 output
tokens. The fast Flash preset remains non-thinking for comparison; the high-thinking
button configures all twelve seats with tools, enabled/high, temperature null
and 32768 output tokens. The compatible v11 native protocol uses auto tool choice
in both modes because the provider rejects required with thinking enabled.
The host still rejects missing or invalid terminal tool actions.

Consult [DeepSeek's API quickstart](https://api-docs.deepseek.com/) for current
model names and [JSON output instructions](https://api-docs.deepseek.com/guides/json_mode/)
for the response-format behavior. This application does not silently replace
retired model aliases; provider-side alias changes remain possible, so the
archive records the returned model identifier when provided.

## OpenAI API

Set `OPENAI_API_KEY` and select `provider: "openai"` with an explicit supported
model. This is API billing, independently selected from subscription-backed
usage. The adapter calls the public Responses endpoint, sets `store: false`,
requests a JSON object, and supplies no tools or previous response identifier.

Models differ in which sampling settings they accept. Set `temperature` to null
for models that do not accept it. An unsupported model or setting produces a
visible error and stops progress instead of changing the frozen configuration.

## OpenAI subscription-backed usage

Select `provider: "openai_subscription"`. The adapter accepts an explicitly
supplied `OPENAI_CHATGPT_ACCESS_TOKEN` obtained through an authorized **Sign in
with ChatGPT** integration with ChatGPT plan-usage permission. It does not read
Codex credential files, reuse browser cookies, invoke a coding agent, or grant
the player access to a filesystem. An ordinary identity-only sign-in is not
enough to authorize inference.

The initial implementation does **not** implement the OAuth registration,
browser sign-in, token exchange, account model picker, or refresh-token storage.
Integrate those steps using the [official Sign in with ChatGPT documentation](https://developers.openai.com/siwc/token-sharing-open-source)
before treating subscription connection as a complete user-facing feature.
Supplying a token is an advanced local integration path, not an assertion that
any ChatGPT subscription or existing Codex token can be used for this application.

Set both `temperature` and `max_tokens` to **null** for this provider; configuration
validation rejects other values because the documented plan-usage route does not
support those inference fields. Speech and notes still have fixed character
limits, but those are not inference-token spending caps. Select a model slug from
the authorized account's current model catalog; there is no hardcoded claim of
account access. The adapter uses `https://api.openai.com/v1/responses` with
`store: false` and `stream: true`, and accepts output only after a completed event.
It omits unsupported fields and persistent conversation references. See
[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
and [preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

This route has account eligibility, consent, regional, and usage constraints.
An expired or rejected token pauses inference. Reconnect through the authorized
sign-in flow and update the server credential; do not substitute another provider
or model. A future connection UI must clearly identify when ChatGPT plan usage is
active and provide account usage controls.

## Failures, records, and replay

Transient network failures, HTTP 429, and HTTP 5xx receive at most two transport
attempts. Other failures pause immediately. Successful responses within a failed
simultaneous batch are retained for an explicit retry; no partial batch reaches
the referee and no player sees another uncommitted action. A referee rejection
discards the batch for a clean explicit retry without automatic substitutions.

New games default to strict first-attempt validation: an invalid response pauses
the game and remains available for diagnosis. Safe `validation_details` classify
wrong action types, illegal options, extra/missing fields, JSON syntax positions,
and token truncation alongside the exact credential-free request and final text.

Parsed but invalid actions are retained in the private inference log with
`rejected: true`. Optional `allow_format_repair: true`, chosen before the game,
permits at most one automatic format-repair request using that player's unchanged
observation, the same legal options, and its own rejected action. Both attempts
are recorded, and only the accepted
response can update the game or private notes. Authentication/network failures
do not trigger format repair. These invalid attempts remain visible to evaluation
instead of being silently normalized into legal choices.

Malformed, non-object, or blank action text is also retained with safe model and
usage metadata and can receive that one repair attempt. Token-truncated output
is recorded but pauses without an automatic retry at the same insufficient
budget. Provider reasoning and transport response bodies are never attached.

Requests in one simultaneous batch run with up to four workers, each receiving
only its own frozen input. Results are recorded in decision order, not network
completion order. A failed seat does not discard other successful paid responses,
and the referee cannot see or apply a partial batch.

The earlier `player-v1` adapter did not retain action content rejected inside the
provider validator. Such old failures identify the decision stage but cannot
prove which field was wrong. The `player-v2` protocol adds decision-specific JSON
examples and explicitly disallows wrappers and extra keys.
Subsequent live testing captured a concrete protocol confusion: an AI returned
`{"type":"json_object"}` as its action. `json_object` describes serialization,
not a legal game action; it must never replace the task's supplied action type.
The `player-v3` prompt fixes a concrete path mismatch: the model's actual user
message contains `decision.options`, whereas earlier instructions referenced a
nonexistent `input.decision.options` wrapper. This is a confirmed prompt defect,
not proof that it caused every observed failure. See [the diagnosis](prompt-diagnostics.md).

Trusted local archives can be restored with `python3 -m werewolf --resume PATH`.
The engine reconstructs state from accepted actions and checks historical views;
it never calls a provider during restore. Valid cached responses are remapped to
the restored batch, so completed actions are not inferred again. New requests
continue through the current protocol with frozen model/player settings.

Trusted local exports contain provider-neutral player requests, exact JSON wire
bodies, parsed actions, returned model identifiers, numeric usage, and action
text. They exclude authorization headers and provider reasoning fields. Do not
share an omniscient archive with players during a game. Replays use recorded
historical views without inference; later role reveals do not leak backward.

OpenAI documentation was checked on 2026-11-08. Subscription integration details
and provider capabilities should be verified again when implementing sign-in.


DeepSeek thinking HTTP requests allow 300 seconds of socket waiting, compared
with 90 seconds for fast mode. Native tool calls still have one transport
attempt; a connection failure is recorded and pauses for an explicit retry.
Safe diagnostics retain exception class, wait limit and attempt count, not raw
exception text, credentials, or provider bodies. An in-flight retry clears the
stale UI error while retaining the original inference failure in the archive.

## Codex Harness validation

The experimental `werewolf/codex_harness.py` adapter uses the installed Codex
Harness through `codex app-server` over stdio. Authentication stays inside Codex;
the adapter checks for a ChatGPT login and exact model/effort availability. It
does not extract OAuth tokens, call a private subscription endpoint, use an
OpenAI API key, or fall back to another model or billing path.

Checked against [official App Server documentation](https://learn.chatgpt.com/docs/app-server)
and local `codex-cli 0.166.0` on 2026-11-09. This validates Codex Harness separately
from the earlier direct `openai_subscription` HTTP adapter described above.

### Thread and event lifetime

- A `CodexGameHarness` owns a game scope and one app-server connection. Its
  `bind(CodexPlayer(...))` returns the same seat thread throughout that scope;
  changing a bound player's configuration is rejected. A new game has new threads.
- Each seat receives only detached authorized observations, never an engine,
  runner, full archive, spectator endpoint, or another seat's thread identifier.
- `feed()` uses `thread/inject_items` to append complete authorized event bundles
  without starting inference. Per-seat offsets are acknowledged before advancing;
  identical deliveries are no-ops. Changed history, rollback, identity changes,
  and non-Wolf wolf-channel deliveries are rejected.
- `decide()` starts another turn on the same thread. A per-seat lock keeps the
  frozen decision snapshot stable while a turn is active. Incoming updates wait
  until that turn completes; this version does not use mid-turn `turn/steer`.
- Dynamic `game_tool` is a stable native gateway. Each turn supplies the current
  catalog, and the host validates its name and parameters against a fresh
  `SeatToolHarness`. Old actions, cross-seat parameters, reads after submission,
  multiple actions, and public protocol-field contamination are rejected.
- Private notes are staged with `write_my_notes`; the caller receives them only
  with a successful complete action. An interrupted/invalid turn returns no
  action and does not commit a new plan.

Threads request no execution environments or workspace roots, use an empty
temporary working directory, and load no project instruction files. Shell,
browser, apps, plugins, memories, hooks and configured MCP connections are
disabled for the app-server process without modifying the user's configuration.
Some built-in utility names may remain discoverable. Earlier synthetic probing
confirmed a file operation was blocked with “No usable execution environment”;
the temporary canary was not created. These controls are not an operating-system
security boundary against a compromised Codex runtime.

Only game tool callbacks, numeric token usage, compaction notices and terminal
status are retained by this adapter. Ordinary assistant streaming text and
reasoning events are discarded rather than published as speech or saved in its
diagnostic trace. The host publishes only a validated `action_speak` or
`action_discuss` payload. There are twelve utility calls per decision, bounded
input/tool-output sizes, and a 300-second whole-turn deadline. App Server owns
its internal inference loop; this adapter does not count or constrain each
underlying model request as the DeepSeek HTTP loop does.

### Reproduce without an existing private archive

After installing Codex and signing in with `codex login`:

```sh
python3 scripts/verify_codex.py --synthetic --decisions 3
python3 scripts/verify_codex.py --synthetic --seats 1,5,10 --decisions 2 --exercise-tools --output artifacts/codex-utilities.private.json --summary artifacts/codex-utilities.json
```

These commands consume subscription usage. They create fresh fictional input
with the real referee engine and send only each selected seat's view. The
scripted source timeline remains fixed: model proposals do not alter it. They
are protocol/capability tests, not a complete AI game or strategic comparison.
No existing private archive is opened in `--synthetic` mode.

The first actual attempt to use the old private game archive was rejected by
automatic approval review for sending its hidden-role/private observation data
to another provider. That command did not execute. Validation instead used only
the new synthetic data above.

| Actual GPT-6.1 Sol / high test | Threads | Valid actions | Failures | Utilities |
| --- | ---: | ---: | ---: | --- |
| All twelve seats, three decisions each | 12 | 36 | 0 | Terminal actions across all six roles |
| Seer, Wolf and Witch, two decisions each | 3 | 6 | 0 | Six own-note reads, six private-result reads, two wolf-chat reads and six private-note writes |

Both cohorts reused each seat's thread and started zero model turns during idle
event injection. The first cohort reported 885,410 input tokens (628,992 cached),
5,261 output tokens including 548 reasoning tokens. The utility cohort reported
191,433 input tokens (142,464 cached), 1,549 output tokens including 108 reasoning
tokens. Usage is the difference in thread cumulative counters, not `last`, which
only measures the final model request in a turn. An initial two-seat smoke test
used that incomplete `last` counter and is excluded from these usage totals.
Effort was set to high; these small tasks do not establish strategic strength or
cost efficiency for a full game.

Aggregate reports are `artifacts/codex-thread-validation.json` and
`artifacts/codex-utilities.json`. Raw authorized inputs and tool results remain
local in corresponding `*.private.json` files, ignored by Git. Offline auditing
requires no provider calls:

```sh
python3 scripts/verify_codex.py artifacts/codex-thread-validation.private.json --audit-only
```

The audit reconstructs event-prefix delivery, current briefings and tool catalogs,
every seat-local tool result, private-note continuity and the legal terminal
action. Synthetic tests additionally reject cross-seat requests, changed/future
history, wrong-thread events, tampered traces, and public field bleed.
All 206 Python tests passed, including fourteen new Codex/runtime-audit tests.

The validation threads currently live in memory for the game harness lifetime.
Disconnection, a lost delivery acknowledgment, or a failed turn marks the seat
unusable and requires explicit recovery; there is no silent context reset or
format retry. Automatic restart/resume, long-context compaction and a full live
AI game have not been validated. The spectator UI is not connected to this
experimental adapter yet. This milestone verifies the agreed persistent-thread
and native-tool foundation before that integration.
