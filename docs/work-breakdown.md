# First milestone work breakdown

The first implementation was divided among three subagents, with the primary
agent responsible for shared interfaces, integration, review, and verification.
Each area is committed independently after its relevant checks pass.

| Area | Implementation | Verification |
| --- | --- | --- |
| Rules and information isolation | `werewolf/engine.py` | Role abilities, Sheriff and exile flow, victory precedence, atomic actions, private projections, paired hidden-state checks |
| AI players and orchestration | `werewolf/providers.py`, `werewolf/runner.py` | Frozen configuration, stateless per-seat requests, private notes, retries, mocked provider HTTP, historical replay |
| Bilingual spectator experience | `web/` | English/Chinese interface, fixed game speech language, three perspectives, playback, setup, replay, safe text rendering |
| Local application integration | `werewolf/server.py`, `werewolf/__main__.py` | Background stepping, read-only replay, same-origin controls, local HTTP boundaries, complete bilingual scripted games |

The implementation has no runtime dependencies beyond Python's standard library.
The browser uses ordinary HTML, CSS, and JavaScript with no external assets.

## Remaining before live AI milestone sign-off

- Expand live game evaluation beyond DeepSeek Flash's verified connection path:
  check complete-game strategic quality, long-context behavior, latency, and
  usage across providers. OpenAI transports have not had live validation.
- Implement authorized subscription browser sign-in, token refresh, and model
  discovery. The token transport alone is not a complete connection experience.
- Review real-game transcripts for strategic quality and tune fixed prompts and
  personalities in subsequent versioned games, preserving fresh-game evaluation.
- Expand adversarial information-boundary tests when adding tools, summaries,
  new roles, context shortening, or provider conversation features. No such access
  should be enabled without revisiting the isolation assumptions.

## Next-stage features

Cross-game memory is intentionally disabled. Later work should specify persistent
player identity, retention and retrieval budgets, and which past public events,
own experiences, and postgame reveals may be recalled. Keep fresh-game and
persistent-player evaluation series separate.

Tournament statistics, voice generation, richer animations, and additional role
sets can build on the same rules and event boundaries after the local game and
live provider path are verified.
