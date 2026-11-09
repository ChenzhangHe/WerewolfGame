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
traces. No substitute action is created. Tool mode currently supports disabled
thinking only; select JSON mode for thinking-enabled evaluations.

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
is never forwarded or archived; action content and tool transcripts are private
archive material.

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
