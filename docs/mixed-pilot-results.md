# Mixed-provider twelve-game pilot: no valid skill outcomes

All twelve preregistered games were attempted. **Zero completed**, so this run
cannot estimate a skill difference or provide a meaningful Elo ranking. Both
entries remain at their prior, 1500 with an approximate marginal interval of
1100–1900. These numbers describe the declared prior, not measured equality.
The rating output explicitly says `no-valid-outcomes-prior-only`.

The [rating mechanism](ratings.md) and [experiment policy](mixed-pilot.md) were
committed and pushed before the season ended. No failed game was replaced or
scored as a defeat. No retries, format repair, default actions or seat-thread
recreation were used. All games kept their original model/prompt/settings.

## Attempts

Each game started with six `gpt-6.1-sol` high Codex seats and six DeepSeek Flash
high-thinking v12 native-tool seats. Complementary assignment pairs balanced
planned role exposure. Every attempted game stopped at its first failed batch.

| Game suffix | Last day | Committed batches | Committed actions | Stop reason |
| --- | ---: | ---: | ---: | --- |
| 01 | 1 | 0 | 0 | DeepSeek action followed by a private note write in the same response |
| 02 | 2 | 43 | 135 | DeepSeek request timeout |
| 03 | 1 | 8 | 31 | DeepSeek public speech contained a closing tool-field tag |
| 04 | 1 | 36 | 108 | DeepSeek request timeout |
| 05 | 1 | 34 | 103 | DeepSeek request timeout |
| 06 | 1 | 4 | 10 | DeepSeek added an `action_run` argument to a run action |
| 07 | 1 | 12 | 41 | Codex turn timeout |
| 08 | 1 | 7 | 27 | DeepSeek added a `parameters` argument to a pass action |
| 09 | 1 | 4 | 10 | Four DeepSeek nomination requests timed out |
| 10 | 1 | 1 | 4 | Three DeepSeek attack requests timed out |
| 11 | 1 | 0 | 0 | Four Codex discussion turns timed out |
| 12 | 1 | 0 | 0 | Four DeepSeek discussion requests timed out |

Game IDs have prefix `pilot-12000-`. Both providers used existing 300-second
limits; DeepSeek's limit is per HTTP request and Codex's is per complete turn,
so these are different timeout units. Across failed batches there were 14
DeepSeek request timeouts, five Codex turn timeouts and four protocol failures.
The table attributes the location of the observed failure, not its root cause.

The host committed 469 actions in 149 batches, with 46 public speeches and zero
explosions. It obtained 495 successful terminal responses; 26 belonged to failed
simultaneous batches and were never committed. Partial-game strategic behavior
and the absence of explosions do not establish comparative playing strength.

## Isolation and replay checks

Every saved partial game independently replayed to the exact referee state.
Audits checked observations and legal options against that state, own committed
notes, successful Codex inputs/event streams and DeepSeek's complete native
request/tool trace, including its failed attempts. Checks found no unauthorized
information in the audited inputs or tool results.

All 12 game scopes and 72 Codex thread bindings were distinct. All 72 initial
own identities matched their referee-authorized seat. The five failed Codex
traces had their actual input, binding and delivered event prefix additionally
checked; they contained no game calls. This extra check matters because the
normal successful-turn trace auditor skips failed Codex records. No final
all-role reveal was delivered to an active player thread.

Reported usage includes about 25.55M Codex input tokens (23.67M cached), 29,552
output tokens, and 2.17M DeepSeek prompt/421,280 completion tokens. Reasoning is
included in completion/output totals. Usage for requests that timed out without
a response is unknown. We did not calculate API cost or subscription savings.

## What this experiment established

The fixed scoring pipeline correctly refuses to manufacture a ranking from
incomplete games. Reliability currently prevents this configuration pairing
from producing skill evidence under the strict stop-on-error policy.

A credential-free reachability check after the run received HTTP 401 promptly
from both providers' model-list endpoints. This only establishes endpoint
reachability at that time; it does not diagnose generation timeouts, quota,
service load, backoff, or latency. The Codex reader does not retain general
error/retry notifications, limiting retrospective diagnosis of those turns.

Before another rated season, investigate transport and sanitized error/backoff
metadata, then separately validate DeepSeek's native tool argument/ordering
contract. In particular, a valid action plus a private note in reverse order
and malformed extra argument wrappers are protocol interoperability issues;
the public-text delimiter guard prevented publication of its malformed output.
Any recovery policy or prompt change must receive a new configuration/protocol
version and a new preregistration rather than modifying this season's records.

## Evidence

- [Aggregate results](../artifacts/mixed-pilot-results.json)
- [Failure and isolation diagnostics](../artifacts/mixed-pilot-diagnostics.json)
- [Prior-only Elo output](../artifacts/mixed-pilot-ratings.json)
- [Frozen rating policy](../artifacts/mixed-pilot-rating-policy.json)

Raw seat inputs, native traces and exact assignments remain in ignored local
`*.private.json` files. Independent audit can be rerun with
`python scripts/play_league.py --audit artifacts/pilot-12000-01.private.json`.
The application test suite passes 217 tests, including rating recovery,
faction-bias separation, failure exclusion and mixed-provider isolation tests.
