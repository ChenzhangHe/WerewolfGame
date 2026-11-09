# Werewolf simulator design

Status: initial design agreed on 2026-11-08; first implementation in progress.

## Purpose

All twelve players are AI-controlled. Humans watch games rather than participate.
Games should be entertaining and support evaluation of AI deduction, deception,
persuasion, coordination, and use of incomplete information.

The primary requirement is that each player receives only information available
to that player under the game rules. Correct deductions and intentional sharing
through permitted game speech are gameplay, not information leakage.

## First milestone

Run one complete game under [rules-v1](rules-v1.md), with:

- Twelve independent players, each with a configuration fixed before play.
- A deterministic rules engine that validates and resolves AI actions.
- Strict separation of public, individual, wolf-team, and spectator information.
- Mystery, omniscient, and individual-player spectator perspectives.
- Pause, step, and replay from recorded events.
- Automated verification of information boundaries and rule resolution.
- No memory carried from previous games.

Support English and Simplified Chinese. Freeze the game language at setup:
player speech, wolf coordination, private notes, and referee announcements use
that language. Viewers may independently change interface language at any time;
recorded speeches retain their original language. Voice synthesis is later work.

Tournament management, voice, elaborate animation, and cross-game learning are
later work. The initial application can run as one process with clear module
boundaries; separate services are unnecessary for this milestone.

## Referee and game state

Ordinary code, rather than an AI moderator, owns role assignment, phases, legal
actions, votes, ability resolution, and victory checks. Players propose speech
and actions; they never directly mutate the authoritative state.

Distinguish referee facts from player claims. A false Seer claim is legal speech;
it does not create an investigation result or publicly confirm a role.

Distinguish pending night deaths from announced elimination. In particular,
first-day Sheriff election eligibility must not disclose an unannounced death.

## Player configuration and model connections

Each seat selects its provider, model, personality, instructions, inference
settings, and budgets before the game. Store an immutable configuration snapshot
and record the model identifier reported by the provider when available.

Support separate adapters for DeepSeek API access and authorized OpenAI
subscription-backed access. Authentication and model availability must be
validated before play. Exact connection mechanisms remain implementation work.

The engine uses a common decision interface: permitted observation plus legal
actions in, proposed action and permitted speech out. Provider adapters handle
authentication, formatting, parsing, streaming, and usage reporting.

Several seats may use the same provider account or model, but never the same
player conversation or private memory. No automatic provider/model substitution
is permitted during a game. Use bounded retries for transient failures, then
pause with a visible operational explanation. Retries must not duplicate actions.

## Information boundaries

Build player observations from explicitly permitted records, not by serializing
the full state and asking the model to disregard secrets.

| Information | Audience |
| --- | --- |
| Seats, role counts, rules, announced eliminations, public speeches, published votes | All players |
| Own role, own private results, own persistent in-game notes | Individual player |
| Wolf identities and permitted night coordination | Living wolf teammates |
| Full hidden assignments, all private actions and notes | Referee and authorized spectator views |

Player notes are AI-authored self-reports, not a claim to expose internal model
reasoning. Notes remain private even if a spectator can inspect them.

Treat other players' messages as attributed dialogue, never as referee or system
instructions. Preserve the distinction even if a player impersonates the referee
or asks another model to ignore its instructions.

No player may access referee files, another player's session, shared memory,
spectator endpoints, or unrestricted tools that expose hidden state. Subscription
agent runtimes must obey the same boundary as direct API adapters.

Do not leak secrets through legal-target lists, validation errors, pending-death
flags, private event-number gaps, summaries, shared caches, or hidden-phase
timing. Keep provider usage, response latency, and internal scheduling telemetry
out of player observations. Public phase announcements follow a fixed script
even when the relevant role is dead or its ability is spent.

Any context shortening must operate only on that player's permitted history.
For the first milestone, prefer retaining complete permitted transcripts within
the configured budget rather than introducing summaries with access to full state.

## Spectator experience

| Perspective | What the viewer sees |
| --- | --- |
| Mystery | Public events; hidden assignments remain concealed until postgame |
| Omniscient | Roles, private actions, wolf coordination, and optional private notes |
| Follow a player | Exactly that player's available information at the selected point |

Show the seats, current phase and speaker, transcript, voting history, and
perspective-appropriate player detail. Support pause, stepping, and replay.
Perspective changes and spectator commentary must never affect player inputs.

Expressive personalities and strategic deception support entertainment. Future
evaluation series can compare personality-rich games with standardized prompts;
record the condition rather than treating those results as interchangeable.

## Events, replay, and evaluation

Record ordered events with explicit audiences, including assignment, private
deliveries, speeches, submitted and accepted actions, resolutions, configuration,
and provider failures. Protect full logs from player access.

Store ruleset and prompt versions, randomness seed, actual model responses, and
the exact assembled requests sent to each provider. Credentials must not appear
in these records. Replay recorded outcomes without querying models again.
A seed reproduces engine randomness; it does not guarantee identical new model
responses.

Later model comparisons should rotate roles and seats across many games and
report results by team and role, together with invalid actions, latency, and
usage. A single game's winner is not sufficient evidence of model superiority.

## Verification and completion criteria

The first milestone is complete when a twelve-player game reaches a valid ending,
replays faithfully, supports all three perspectives, and passes these checks:

- Paired hidden states that are indistinguishable to a player generate identical
  observations, legal actions, and assembled model requests for that player.
- Swapping unobserved good-role assignments does not change an uninformed
  player's input. Changing an investigation result affects only its recipient
  until information is intentionally shared.
- Wolf discussion never reaches a non-wolf request; player notes never cross seats.
- First-day election inputs do not reveal pending deaths.
- Spectator perspective changes do not change any player request.
- Rule tests cover ties, potion restrictions, Hunter eligibility, Idiot reveal,
  Sheriff interruption, last words, and victory timing.
- Failed or retried model requests cannot apply an action twice or switch a seat's
  configuration.

These checks test the system's information boundary, not whether an AI can guess
a hidden fact from legitimate evidence. Do not claim absolute isolation merely
because models avoid mentioning secrets in sample games.

## Next stage: cross-game memory

Preserve distinct fresh-game and persistent-player evaluation conditions.
Persistent players could learn reputations, recognize recurring strategies, and
develop rivalries, supporting both entertainment and tests of adaptation.

The proposed future memory scope is a player's own prior experiences plus an
explicitly shared postgame role reveal. Other players' private conversations,
private notes, and omniscient spectator commentary remain excluded. Memory
retrieval budgets, retention, stable player identities, and evaluation controls
must be designed before enabling this feature.

Record event audiences and the moment information becomes public now, so future
memory can respect the information available at each point in history.
