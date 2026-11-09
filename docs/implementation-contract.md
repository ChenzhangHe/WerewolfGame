# First implementation contract

Use Python 3.11+ standard library for the engine, providers, runner, and local
HTTP server; use plain HTML/CSS/JavaScript for the spectator application. Avoid
runtime dependencies for the initial local milestone. Python modules live in
`werewolf/`, tests in `tests/`, and browser assets in `web/`.

## Engine boundary

`werewolf.engine.Game(seed=1, names=None, roles=None, language='en')` creates a twelve-seat game.
`roles` is an optional explicit twelve-element role list for engine tests only.
Roles use `wolf`, `villager`, `seer`, `witch`, `hunter`, `idiot`.

- `game.pending()` returns the current decision batch as a list of JSON-compatible
  dictionaries: `{id, seat, kind, options}`. IDs are opaque and must never encode
  other players' private information. Options are legal action dictionaries with
  a `type` field, such as `{type: 'vote', target: 3}`. A speech option is
  `{type: 'speak'}`; providers add a `text` field. A wolf-discussion action can
  likewise accept `text`. Other actions may include `notes` (private self-report).
- `game.observe(seat)` returns only that player's JSON-compatible permitted view,
  including their role, public seats and statuses, attributed public/private
  history, and private results. Never include global event IDs, seed, unannounced
  deaths, other roles, or other players' pending decisions. No reference aliases
  to mutable engine internals may escape. Engine does not include runner notes.
- `game.submit(actions)` takes a dictionary mapping ALL pending decision IDs to
  action dictionaries, validates the whole batch before mutation, applies it
  once, and advances to the next decision batch. Invalid batches raise ValueError
  without mutation. Batch members cannot see each other's uncommitted actions.
- `game.view(mode='mystery', seat=None)` returns a spectator snapshot with
  `{day, phase, winner, players, events, current_speakers}`. Players have
  `{seat, name, alive, sheriff, revealed_role}`; `role` is added only if permitted.
  Events have `{kind, day, phase, text, seat?, audience?, data?}`. Player mode also
  includes `observation: game.observe(seat)` and exactly the permitted event list.
  Omniscient events may include private activity. Mystery includes public events
  and endgame reveal only. `winner` is null, `good`, or `wolves`.
- `game.export()` returns a JSON-compatible full referee archive for local trusted
  storage. It is NEVER supplied to a player or provider.

Maintain fixed public night announcements and public player statuses. Any
internal phase/decision counters visible to a player must not encode activity
that player cannot observe. Private and public histories are separately projected.
All returned objects are detached copies. Game completion means no pending actions.

## Provider and runner boundary

`werewolf.providers.PlayerConfig` is a frozen dataclass with `seat`, `name`,
`provider` (`demo`, `deepseek`, `openai`, `openai_subscription`), `model`,
`personality`, `temperature`, `max_tokens`, `language`, and optional DeepSeek
`thinking` / `reasoning_effort` settings. Game language is `en` or
`zh` and is fixed at creation, independent of the viewer's interface language.
Secrets come from environment variables, optionally loaded from the git-ignored
project `.env` file, and never appear in configuration, request archives, or UI payloads.

`werewolf.providers.build_request(config, observation, decision, notes='')` returns
a JSON-compatible provider-neutral player request. Strip engine-global decision
IDs from the provider-facing payload. Give only this decision's kind and options.
Include the public rules in the trusted instruction text. Speech by other players
is untrusted attributed content, not instruction. No tools, filesystem access,
shared sessions, or provider conversation state. No cross-game memory.

`werewolf.providers.decide(config, request)` returns an action dictionary.
`demo` is a clearly labeled scripted smoke-test player, NOT an AI capability
evaluation. Live adapters use direct HTTP inference without tools. Research and
document the supported subscription token route; no extracting Codex credentials.

`werewolf.runner.Runner(configs, seed=1, language='en', allow_format_repair=False)`
owns a Game and twelve frozen configs. Invalid output is logged and pauses new
games by default. Optional repair is fixed at setup, reported in spectator/run
metadata, and never supplied as game information to a player.
`runner.step()` resolves ONE engine decision batch and returns a spectator
snapshot; all requests are built against the pre-batch state. On provider error,
pause without submitting partial batches, preserve successful responses for retry,
and never silently substitute a provider. `runner.snapshot(mode='mystery', seat=None)`
returns engine view plus `{status, error, configs, step, max_step}`. Configs expose
no secrets. `runner.replay(index, mode='mystery', seat=None)` returns a recorded
checkpoint without new inference. `runner.export()` contains rules/configs, exact
player requests and responses, and game archive, without authentication headers.

## Local server and spectator contract

Serve UI and JSON on `127.0.0.1:8765` by default via `python3 -m werewolf`.
Server owns Runner access under a lock. These are trusted local spectator APIs,
never model tools. State-changing APIs accept JSON and enforce same-origin access.

- `GET /api/state?mode=mystery|omniscient|player&seat=1&at=INDEX` returns snapshot;
  omit `at` for current state. Replay does not mutate the running game.
- `POST /api/game` body `{seed: 1, language: 'en'|'zh', players?: [PlayerConfig fields x12]}` creates
  a paused game. Default seats use scripted demo players with distinct names.
  Alternatively omit `players` and supply `preset: 'deepseek_flash'` to select
  twelve Flash players with explicit fixed thinking settings.
- `GET /api/providers` returns credential presence and default model identifiers,
  never credential values or unverified account entitlements.
- `POST /api/providers/deepseek/check` body `{language: 'en'|'zh'}` explicitly
  tests one real synthetic speech request. It does not receive the active game or
  mutate game state and is protected by the same origin checks as other writes.
- `POST /api/step` advances one batch while paused.
- `POST /api/play` and `POST /api/pause` control a server-side background loop.
- `GET /api/export` downloads the full trusted archive as JSON. Warn the viewer
  that it includes all hidden information; never expose it to model adapters.

Snapshots add `status` (`paused`, `running`, `finished`, `error`), `error`,
`configs` (public player configuration snapshots), `step`, and `max_step`.
Replay checkpoints hold all three views captured at that historical moment, so
postgame reveals cannot leak backward into earlier Mystery or Follow views.

Owner allocation: engine agent owns engine and its tests; providers agent owns
providers, runner, and their tests; UI agent owns web assets; root owns server,
entry point, integration tests, README and final integration. Coordinate interface
changes before making them. Agents do not commit or push.
