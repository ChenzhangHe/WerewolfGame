# Prompt failure diagnosis

## What the saved evidence establishes

The original `player-v1` wolf-attack rejection has no saved response body; the
old adapter discarded it before the runner could record it. Its exact invalid
field is unrecoverable. Later private logs contain concrete examples:

| Failure | Evidence | Interpretation |
| --- | --- | --- |
| Invalid action type | A Seer task returned `type: json_object` instead of `investigate` | Valid JSON can still be an invalid game action |
| JSON syntax error | An otherwise plausible object ended with an extra `)` | Protocol syntax failed independently of strategic choice |
| Extra output | A complete object was followed by simulated system-warning messages | The response boundary was not respected |
| Token truncation | Completion usage reached the configured cap, with no complete final action | An incomplete generation is separate from an illegal action |

The simulated warning markers were absent from the application-supplied
instructions and player data for the captured case. They appeared in the model
output. This does not establish what happened inside the provider's hidden
context; no provider reasoning is retained or used for diagnosis.

## Confirmed application prompt defect

The wire adapter serializes a user message shaped as:

```json
{"observation": {}, "decision": {"options": []}, "private_notes": ""}
```

Earlier instructions said to choose from `input.decision.options`, but there is
no `input` wrapper in that message. `player-v3` corrects the reference to
`decision.options` and states the real top-level shape. Regression tests inspect
the actual serialized provider message, not just the provider-neutral object.

`tests/fixtures/player-v2-instructions.txt` preserves public instructions built
from a synthetic Seer decision, with no real game observations or private notes.
It documents the old path mismatch without publishing private archives.

## Candidate contributors, not proven causes

- The old universal speech example could prime the wrong action during a
  non-speech task. Later prompts already replaced it with task-specific examples.
- The system prompt contains the whole repository rules document, including
  source links and implementation prose that a player does not need.
- Sorted wire keys put the decision before a potentially long observation,
  while private notes appear last. Keeping the current task close to the final
  response may make the boundary clearer.
- Mentioning invalid serialization names in negative instructions could also
  prime unwanted tokens. This requires controlled comparison, not an assertion.

The successful 265-request fast-mode run does not isolate a prompt effect:
thinking mode, seeds, and protocol versions differed across diagnostic games.
Measure first-attempt validity on matched synthetic cases before claiming a
causal reduction in failures. Do not resend private archived games externally
as an implicit debugging step.

## Logging and recovery policy

New games have `allow_format_repair: false`. A failure pauses immediately and
keeps the exact credential-free messages, raw final action content, parsed
output when available, model/usage metadata, and structured validation category.
JSON failures include parser reason and position; action failures identify
expected types and invalid field names. Details stay in the private archive.

An explicitly enabled repair policy permits one separately logged correction;
it is recovery, not evidence of first-attempt validity. The policy cannot be
changed midgame. Legacy archives preserve their previous policy on restore.

## Implemented next step: player tool harness

New DeepSeek Flash games use a short briefing and seat-scoped read tools for
history, rules, and private results. Only the current turn's action tools are
exposed. The referee validates and resolves proposals atomically. Exact per-hop
wire requests, tool calls, results, and failures are retained in private archives.
Tool mode does not invoke format repair. See [the harness contract](tool-harness.md).
