# Player providers and bilingual games

The default `demo` provider is a deterministic scripted smoke-test player. It
does not call an AI model and must not be used as evidence of AI capability.
Real inference uses one of the adapters below. These adapters have mocked HTTP
coverage; they have not been validated against a live paid account in this work.

## Configuration and language

Configure all twelve seats before starting the game. `provider`, `model`,
`personality`, `temperature`, and `max_tokens` are frozen for that game. Game
language is `en` (English) or `zh` (Simplified Chinese), and is copied into every
seat's frozen configuration. Referee announcements and player speech use that
language. Changing the interface language does not translate old speech or alter
an active game. Generated text is instructed to use the game language; model
language compliance still needs evaluation with actual models.

Each inference is stateless and tool-free. Its input contains the selected
player's permitted observation, legal options for their own decision, and that
player's private notes. Other seats' private notes, referee archives, hidden
assignment seed, global decision IDs, tools, and provider conversation/session
continuations are never supplied. All requests for a simultaneous batch are built
before any batch action is committed.

Secrets are read from the server process environment only. Do not put credentials
in player configuration JSON, URLs, personalities, source files, or commits.
Credential presence is checked when creating a game. Presence does not establish
validity, account entitlement, or model availability; successful inference is the
real access check. No automatic provider, model, or billing-path fallback occurs.

## DeepSeek API

Set `DEEPSEEK_API_KEY` in the terminal that starts the server. Select
`provider: "deepseek"` and an explicit model name available to the account. The
adapter calls `https://api.deepseek.com/chat/completions` with JSON output enabled.
It passes the configured temperature and token budget when they are not null.
The prompt explicitly requests JSON; incomplete, blank, invalid, or illegal
responses pause the game rather than creating a substitute action.

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

Trusted local exports contain provider-neutral player requests, exact JSON wire
bodies, parsed actions, returned model identifiers, numeric usage, and action
text. They exclude authorization headers and provider reasoning fields. Do not
share an omniscient archive with players during a game. Replays use recorded
historical views without inference; later role reveals do not leak backward.

OpenAI documentation was checked on 2026-11-08. Subscription integration details
and provider capabilities should be verified again when implementing sign-in.
