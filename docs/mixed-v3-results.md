# Repaired season verification — in progress

The v3 season uses the [frozen preregistration](../artifacts/mixed-v3/preregistration.json)
and [v14 native tool protocol](reliability-v14.md). Old failed experiments and
the separate validation game are excluded. No final Elo ranking is claimed
until the scheduled season finishes.

The first complementary assignment pair completed and passed independent
referee replay and provider input/tool audits:

| Game | Winner | Last day | Actions | Batches | Minutes | Model-corrected transactions | HTTP retries |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 14000-01 | Good | 3 | 190 | 85 | 46.2 | 3 | 2 |
| 14000-02 | Wolves | 3 | 222 | 76 | 34.8 | 2 | 2 |

Both had zero final failed decisions. Rejected native proposals remained in the
trace, with no referee action accepted until the model submitted a valid call.
The remaining scheduled games continue under the same frozen settings.

[Game 1 summary](../artifacts/mixed-v3/pilot-14000-01.json) ·
[Game 2 summary](../artifacts/mixed-v3/pilot-14000-02.json)
