# Console-disconnect recovery

The v3 run completed games 1 and 2, then games 3 and 4 stopped with a host
`BrokenPipeError`. Both interrupted referee states replay independently; their
saved records contain zero model-decision errors. The progress printer raised
its console error into the game loop. The result collector also used a direct
print, so its final aggregate omitted game 3 even though that game's individual
failure summary was saved.

Console output now uses a best-effort sink. A lost pipe, closed console or
terminal I/O failure cannot fail the game or stop collection of other completed
results. A disconnected stdout descriptor is redirected to the null device so
Python's shutdown flush cannot turn a successful process into exit code 120.
Durable game snapshots, summaries and aggregates still use their existing
atomic file writes; those errors remain visible. Terminated Codex subprocess
pipe cleanup is idempotent and tolerates already-closed pipes. Unexpected host
failures now retain safe traceback locations (file/function/line only), without
local variables, credentials or free-form upstream messages.

Regressions cover a complete simulated game with disconnected stdout, collection
of multiple season results after console loss, an actual closed OS pipe including
interpreter shutdown, an explicitly closed stdout object, and subprocess cleanup.
The tests make no model calls.

The individual game summaries have been reconciled into the aggregate: two
completed games, two host interruptions and eight unstarted games. The original
incomplete aggregate is retained as `mixed-pilot-results.console-interrupted.json`.
Interrupted games are not marked complete or replayed as fresh conversations.

This is a host-only repair: player prompts, schemas, models, efforts, languages,
roles, legal actions and game rules are unchanged. The original frozen plan is
preserved. Any remaining execution must record the host revision before starting
new inference, rather than silently changing its source fingerprint.

Long-running verification should own its output independently of a chat/tool
observer: launch it in a new process session with stdin disconnected and stdout
and stderr redirected to a durable local log. Monitoring then reads progress
files or tails the log; closing the monitor does not own the game's lifecycle.

## Resumed execution

The host-only revision is recorded in
[console-execution-amendment.json](../artifacts/mixed-v3/console-execution-amendment.json).
Eleven inference/rules files and the Codex actor/active-RPC ASTs were verified
unchanged against the original preregistration. Matches, roles, configurations
and transport settings remain identical. Only the eight unstarted games resume;
the two host-interrupted games remain unscored.

The resumed worker owns a new process session and a persistent local log. Its
launcher has exited, and fresh progress from games 5 and 6 confirmed it continues
independently. When the runner exits, its supervisor calculates ratings from
audited completed games and records final status. The historic host failures
can make the runner exit nonzero even when every remaining game succeeds.

Operational files are local and ignored: `verification-process.private.json`,
`verification-status.private.json`, and `verification.log` under the season
directory. The application test suite passes 237 tests.
