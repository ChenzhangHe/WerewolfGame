# Mixed-provider v3 pilot — halted

The v3 season used the [frozen preregistration](../artifacts/mixed-v3/preregistration.json)
and [v14 native tool protocol](reliability-v14.md), followed by the explicit
[host-only console repair amendment](../artifacts/mixed-v3/console-execution-amendment.json).
It has stopped with six returned attempts: three completed games and three
unscored failures. Games 7–12 were never started. The new Codex-only pilot is a
separate experiment and does not replace any of these attempts.

| Game | Outcome | Last day | Actions | Minutes |
| --- | --- | ---: | ---: | ---: |
| 14000-01 | Good win; all checks passed | 3 | 190 | 46.2 |
| 14000-02 | Wolves win; all checks passed | 3 | 222 | 34.8 |
| 14000-03 | Host BrokenPipeError; unscored | 4 | 192 committed | 75.9 |
| 14000-04 | Host BrokenPipeError; unscored | 2 | 145 committed | 40.6 |
| 14000-05 | DeepSeek missing tool call, then audit assertion; unscored | 3 | — | 41.7 |
| 14000-06 | Wolves win; all checks passed | 5 | 250 | 79.4 |

Game 5's saved failed decision is seat 7 (Echo), **deepseek-flash/high**, batch 73,
transport `deepseek-native-tools-v14`: a text response had no required native
action call. Its final audit also raises `Native transaction execution order
differs.` That mismatch needs investigation; the failure is not a valid game
outcome. There was no new BrokenPipeError after the console repair. The scheduler
stopped new launches on game 5's failure and collected the in-flight game 6.

All three completed games have zero final failed decisions and pass independent
referee replay plus provider input/tool audits. Game 6 had one recovered Codex
stream-disconnection notification and 21 DeepSeek HTTP retries; these were logged
recoveries, not substituted actions or fresh replacement threads.

The [provisional ratings](../artifacts/mixed-v3/mixed-pilot-ratings.json) use only
the three completed games: Sol/high **1607.06**, DeepSeek Flash/high **1392.94**.
The approximate 95% interval for DeepSeek minus Sol is **−662.50 to +234.24**.
This small, incomplete and role-imbalanced sample does not establish a reliable
ranking. The two original host interruptions and the new failed game remain
visible and excluded, as do the six unattempted games. These ratings do not
include the subsequent Sol/medium versus Terra/low experiment.
