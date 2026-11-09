# WerewolfGame

A Werewolf simulator where every player is powered by AI and humans watch.
The project aims to make games entertaining while providing a trustworthy way
to evaluate deduction, deception, persuasion, and coordination across models.

The local prototype runs complete 12-player games with isolated player views,
fixed player configurations, three spectator perspectives, and historical replay.
It supports English and Simplified Chinese, including player speech and referee
announcements in the language selected before the game.

## Run locally

Requires Python 3.11 or later. No third-party packages are needed.

```sh
python3 -m werewolf
```

Open [the local spectator](http://127.0.0.1:8765). The default twelve players are
**scripted demonstrations**, not AI models. Use Play or advance one decision batch
at a time. In New game, choose the game language and configure all twelve seats
before starting. EN / 中文 changes interface text independently; recorded speeches
retain their original language. Audio generation is not implemented.

Mystery hides roles until postgame. Omniscient exposes private activity. Follow a
player shows that seat's permitted information. Replay preserves what was known
at each recorded checkpoint; postgame reveals do not appear in earlier views.
Pause stops after an in-flight decision batch finishes. Game state is held in
memory; export the full archive before starting another game or stopping the
server. Export includes hidden information and is intended for trusted analysis.

The server listens only on `127.0.0.1`; use `--port 8766` to choose another port.
It is a trusted local spectator application, not a multi-user hosting service.

## Connect AI players

See [provider setup](docs/provider-setup.md). Secrets come from the server's
environment, never player configuration or the browser. Available adapters are
DeepSeek API, OpenAI API, and authorized OpenAI subscription token transport.

Live provider calls have not been exercised in this implementation. Subscription
browser sign-in, token refresh, and account model discovery are still outstanding;
its current adapter requires a token from an authorized integration. No model or
provider is silently substituted after the game starts.

## Verify

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
```

Tests cover paired hidden-state observations, private events and notes, rule
edge cases, immutable configurations, atomic batches and retries, historical
replay, provider transports with mocked HTTP, local HTTP boundaries, and complete
scripted games in both languages. Node is needed only for the JavaScript syntax
check, not for running the application.

## Design and work areas

- [System design and milestone](docs/design.md)
- [Version 1 game rules](docs/rules-v1.md)
- [Shared implementation interfaces](docs/implementation-contract.md)
- [Work breakdown and remaining tasks](docs/work-breakdown.md)
- [Provider connections and limitations](docs/provider-setup.md)
