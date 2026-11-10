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

### Codex Harness validation (ChatGPT subscription)

An experimental validation adapter uses the real `codex app-server` agent loop,
with **one thread per game and seat**, incremental authorized event deliveries,
and the existing seat-scoped game tools. It uses the CLI's ChatGPT login; no
OpenAI API key or manually copied subscription token is required.

```sh
codex login
python3 scripts/verify_codex.py --synthetic --decisions 3
```

This explicitly invokes `gpt-6.1-sol` at high effort and consumes subscription
usage. It generates a fictional timeline without reading an existing private
game archive. Each of twelve seats makes three proposals against fixed snapshots;
this is a capability test, not a complete AI-played game. To exercise private
reads and note writes as well:

```sh
python3 scripts/verify_codex.py --synthetic --seats 1,5,10 --decisions 2 --exercise-tools --output artifacts/codex-utilities.private.json --summary artifacts/codex-utilities.json
```

Results and audit instructions are in [provider setup](docs/provider-setup.md#codex-harness-validation).
The spectator setup still uses the existing providers; this experimental adapter
is currently exercised through the validation command. Threads live for the
validation game's lifetime; automatic restart recovery and compaction have not
been validated. Missing access or a failed turn stops that seat without fallback.

To run complete AI-driven games on new fictional game data:

```sh
python3 scripts/play_codex.py --seeds 9101,9102,9103 --output-dir artifacts/codex-next-run
```

This runs three games concurrently, with two inference workers per game. Every
seat uses GPT-6.1 Sol / high and one thread for that whole game; actual model
actions advance the referee. Existing match files are never overwritten: choose
new seeds or a fresh output directory for another experiment. Completed-game
results are in [the match summary](artifacts/codex-matches.json); the first three
games completed with 707 actions, zero failed attempts, two Good wins and one
Wolf win. Details and limitations are in the provider setup document.

### DeepSeek Flash

1. Obtain an API key from the [DeepSeek platform](https://platform.deepseek.com/).
2. In the repository root, copy [.env.example](.env.example) to a file named
   **`.env`** if you do not already have one. Put your own key in that local file:

   ```dotenv
   DEEPSEEK_API_KEY=your_deepseek_api_key
   ```

   `.env` is ignored by Git. Keep the real key out of source files, screenshots,
   player personalities, and shared archives. Existing `DEEPSEEK_API_KEY` process
   environment values take precedence over the file. Restart the server after
   changing a previously loaded key. The loader reads literal values; it does not
   execute shell expressions or load arbitrary settings.

3. Verify a real, small Flash request. This consumes API usage:

   ```sh
   python3 -m werewolf --check-deepseek --language en
   ```

4. Launch twelve real Flash players with Chinese or English gameplay:

   ```sh
   python3 -m werewolf --preset deepseek_flash --language zh
   # For English gameplay, use --language en instead.
   ```

   Open [the local spectator](http://127.0.0.1:8765) and press **Play**. Startup
   leaves the game paused. Alternatively, start normally, open **New game**, and
   select **Use DeepSeek Flash for all 12**. **Test connection** makes one explicit
   request without revealing or changing the current game.

The preset selects `deepseek-flash` with a **seat-scoped tool harness** and
**thinking disabled**,
temperature **0.7**, and an **8192-token** response limit. Live thinking-mode
tests exhausted both 4096 and 8192 budgets before producing action content, so
thinking is an explicit per-player experiment rather than the viewing default.
You can enable it before a new game in JSON interaction mode, selecting an effort
and leaving temperature unset. Existing games keep their original settings. Change settings before creating a game; they remain fixed
during play. Each player uses only its own authorized context. History and rules are read on
demand through bounded tools; only current legal action tools are exposed. API failures pause
the game without silently replacing a player with a script or another model.
See [DeepSeek's model documentation](https://api-docs.deepseek.com/) and the
[detailed provider setup](docs/provider-setup.md).

**中文说明：** 在项目根目录创建名为 `.env` 的文件，填入自己的
`DEEPSEEK_API_KEY=你的密钥`。不要提交或分享真实密钥；项目已忽略 `.env`。
先运行 `python3 -m werewolf --check-deepseek --language zh` 测试连接，再运行
`python3 -m werewolf --preset deepseek_flash --language zh`，打开本地页面并点击开始。
修改已加载的密钥后请重启服务器。

### Other providers

Available adapters also include OpenAI API and authorized OpenAI subscription
token transport. Those live connections have not been verified. Subscription
browser sign-in, token refresh, and account model discovery remain outstanding;
its current adapter requires a token from an authorized integration. See
[provider setup](docs/provider-setup.md).

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

To explicitly run the current server game for up to three additional day/night
rounds (or until victory), consuming real usage for configured AI players:

```sh
python3 scripts/verify_live.py --rounds 3 --output artifacts/live-check.private.json
```

The script leaves the game paused and saves a private diagnostic archive. It
does not change providers, roles, or player settings. New games pause on the
first invalid player response and retain the exact request, action content,
and structured validation details for prompt debugging. First-attempt failures
are never counted as clean successes.

For JSON-mode players, optional recovery can be enabled before creating a new game with
`--allow-format-repair` (or `allow_format_repair: true` in setup JSON). This allows
one logged correction attempt using only that player's unchanged observation
and legal options. The policy is fixed for the game and is preserved on restore;
older archives retain their original repair-enabled policy.

To continue an interrupted game after restarting the server, use a trusted local
archive downloaded with **Export full archive** or saved by the verifier:

```sh
python3 -m werewolf --resume artifacts/live-check.private.json
```

Restore validates and replays accepted actions without new inference and starts
paused. It preserves player configurations, private notes, and historical views.
Archive files contain hidden information; do not give them to active players.

## Design and work areas

- [System design and milestone](docs/design.md)
- [Version 1 game rules](docs/rules-v1.md)
- [Shared implementation interfaces](docs/implementation-contract.md)
- [Work breakdown and remaining tasks](docs/work-breakdown.md)
- [Provider connections and limitations](docs/provider-setup.md)
- [Live DeepSeek validation results](docs/live-validation.md)
- [Prompt failure diagnosis](docs/prompt-diagnostics.md)
- [Seat-scoped player tools](docs/tool-harness.md)

### Spectator voice and election markers

Player seats show public Sheriff nominations, withdrawals, and election history.
These markers follow the selected replay checkpoint; private nomination choices
are not shown before publication.

Use **Voice off / 朗读：关** above the transcript to enable automatic reading of
new player speech and public referee announcements. Each voiced record also has **Read aloud / 朗读** for manual playback.
The game language chooses English or Chinese independently of the UI language.
Playback uses only local system voices reported by the browser; no additional
API key is needed. Install the corresponding system voice if none is available.
[Local voice identification](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisVoice/localService)
is part of the browser speech API. Voice starts off, history is not automatically
read on enable, and changing perspective, replay, or games cancels old playback.
The live queue is bounded; if narration falls behind it stops with a visible
message, allowing manual selection instead.

Run the browser-logic checks without making model calls:

```sh
node tests/speech.test.cjs
node tests/speech-ui.test.cjs
node tests/election-ui.test.cjs
```

See [the repeated-explosion diagnosis](docs/explosion-diagnostics.md) for the
evidence and the new v5 prompt changes.


For a thinking-enabled native-tool game, open setup and choose **Use Flash · high
thinking / 十二席 Flash · 高思考**. This sets all twelve seats to `thinking:
"enabled"`, `reasoning_effort: "high"`, `temperature: null`, `max_tokens: 32768`,
and `interaction_mode: "tools"`. Settings apply to the next game and stay frozen.
The fast preset remains available. Thinking is passed back only inside one
seat's current decision; reasoning text is not exported or played to spectators.
New games also supply own prior notes, core rules, and hypothetical arithmetic
tools. See [the harness protocol](docs/tool-harness.md) for their information
boundaries and versioned budgets.

The [twelve-game mixed-provider pilot](docs/mixed-pilot.md) compares six Sol
Codex seats and six DeepSeek Flash high-thinking seats per game, with balanced
role exposure, frozen scheduling, per-provider input auditing, and a tentative
team-outcome score board. It is a command-line experiment; it does not replace
the current browser game's configuration.
