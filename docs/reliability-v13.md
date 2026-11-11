# Native-tool reliability fixes

The failed twelve-game pilot exposed four output-contract failures and timeouts
on both providers. Its original evidence remains unchanged. New experiments use
`mixed-league-v2` and distinct configuration IDs; old results are not merged.

## DeepSeek v13

- Uses the documented [strict native function mode](https://api-docs.deepseek.com/guides/tool_calls/)
  on `/beta/chat/completions`. All fields are declared, every object rejects
  extra properties, and fields become required as strict mode requires. The
  adapter removes unsupported length/item keywords. Host validators still check
  complete legal options, output lengths and information boundaries.
- Public speech gets a schema pattern that excludes angle-bracket delimiters
  and limits length. Notes have a separate bounded schema. The native argument
  prompt explicitly forbids wrapping arguments in function-name/parameters
  objects. Malformed public output is never silently stripped or published.
- One valid action and one private note may arrive in either array order.
  Their original native order is retained; the host stages the note, validates
  the action, and commits neither until the entire referee batch succeeds.
  Reads alongside actions and multiple actions remain errors. The trace records
  the transaction's execution order and the auditor reproduces it.
- Reads Chat Completions SSE deltas, including fragmented native function calls,
  reasoning passback and usage. It requires a finish reason **and** `[DONE]`;
  incomplete streams cannot submit partial actions. Raw reasoning remains only
  in the current decision's memory and is hashed/redacted in the trace.
- Socket waits use a 90-second idle budget, with a 900-second per-hop wall budget
  checked between stream frames. A blocking socket read can extend the latter
  by up to the idle timeout. Streaming wire bytes are capped at 16MB.
- Up to three HTTP attempts per hop retry connection errors, incomplete streams,
  HTTP 429 and 5xx, using bounded backoff/Retry-After. Authentication/schema errors
  do not retry. Each attempt's safe status, duration and failure type is recorded;
  no authorization header or free-form server response is logged. Retries use
  the same frozen seat request before any referee action is committed. Usage
  from failed requests without a final usage response remains unknown.

The [Chat Completions stream contract](https://api-docs.deepseek.com/api/create-chat-completion/)
is separate from OpenAI Responses SSE; their completion markers are not mixed.

## Codex

The [app-server error notification](https://learn.chatgpt.com/docs/app-server#errors)
contains structured codes and a `willRetry` flag. The adapter now routes these
notifications to their exact seat/turn, retains only allowed codes and HTTP
status, and lets an SDK retry remain in its existing active turn. Fatal errors
surface immediately with their category rather than becoming a generic timeout.
The complete-turn limit is 600 seconds. The host never recreates an uncertain
thread or silently substitutes another model/action. Failed inputs and executed
tool prefixes now receive the same seat-scope auditing as successful turns.

## Running games and evidence

Waiting-state files update while the host awaits a batch. Already returned paid
responses are checkpointed before other responses finish. Atomic batch commit
and own-note ownership remain unchanged. New seasons use two decision workers
per game, with two games by default, reducing request bursts. Offline auditing
of historical plans remains available after code changes; executing a plan
still requires the exact preregistered source fingerprint and current protocol.

Both real provider canaries passed. Full-game validation and then a new frozen
12-game season are required before claiming the reliability problem resolved.
Do not use old partial games or the validation game as rated outcomes.
