# Role-aware team ratings on an Elo scale

`hierarchical-team-elo-v1` implements the proposed shared ability plus role
adjustment design. It is a custom regularized Bradley–Terry model on an Elo
scale, **not** traditional fixed-K online Elo, TrueSkill, or a full MCMC fit.
The tournament score remains a separate, simpler descriptive measure.

Each completed audited game contributes **one binary outcome**. Its twelve
seats do not become independent wins/losses. Failed/interrupted attempts remain
in the reliability report and do not enter the skill likelihood. Ratings refer
to complete configurations: model, effort, prompt/harness, memory and tools.

## Model

For configuration `m` in role `r`, strength is `mu[m] + delta[m,r]`.
Team strength is the **mean** seat strength: eight equal Good contributions,
four equal Wolf contributions. This avoids making eight seats automatically
stronger than four by adding their ratings. With `D = mean(Good) − mean(Wolves)`:

```
logit P(Good wins) = good_baseline + layout_effect + ln(10) / 400 × D
```

All configurations start at 1500. The priors are fixed before fitting:

| Quantity | Prior |
| --- | --- |
| Shared configuration offset `mu` | Normal(0, 200 Elo points) |
| Role adjustment `delta` | Normal(0, 100 Elo points), centered across configurations per role |
| Good-side baseline | Normal(0, 1 logit) |
| Shared layout effect | Normal(0, 0.5 logit) |

The baseline handles asymmetric faction difficulty. Complementary games in a
pair share a layout intercept, allowing their outcomes to be related. This is
a limited model of shared layout difficulty, not a complete treatment of all
game correlations or strategy interactions. Entry coefficients depend on both
team compositions; identical composition gives no shared ability contrast.

Role deviations shrink toward the configuration's shared component. Centering
across configurations prevents common role offsets from masquerading as a
faction advantage. Priors regularize the decomposition between shared ability
and role deviation; sparse data cannot identify them precisely. Prior widths
are design choices, not learned/calibrated hyperparameters.

The overall rating uses a declared role mix: 50% Wolf, 25% Villager, 6.25% each
special role. Role ratings and the shared component are reported separately.
This makes role exposure explicit instead of rewarding favorable assignments.

## Fitting and interpretation

The dependency-free fitter standardizes coefficients to unit Normal priors and
minimizes regularized logistic loss with damped Newton steps and a Cholesky
solver. It checks convergence and fails rather than emit an unconverged table.
A deterministic batch refit over all valid games avoids arbitrary chronological
ordering and double-counted incremental updates.

The inverse Hessian gives a **Laplace approximation** to marginal posterior
uncertainty. Output includes approximate 95% intervals and pairwise differences
using covariance. These are not frequentist confidence intervals, calibrated
rank guarantees, or full posterior samples. Reported probabilities for games
already in the fit are explicitly in-sample MAP probabilities, not held-out
predictive performance. All outputs remain exploratory, especially at twelve
games. We make no threshold-based assertion that one configuration is superior.

The partial-pooling principle follows standard hierarchical binary-outcome
modeling; see [Stan's primary worked example](https://mc-stan.org/learn-stan/case-studies/pool-binary-trials-rstanarm.html).
Our roster features, Elo conversion, priors and fitter are this project's design.

## Offline calculation

The policy file is frozen separately from the gameplay preregistration. Adding
this rating mechanism does not change running game prompts or settings.

```sh
# One-time declaration, before examining completed outcomes; refuses overwrite.
python scripts/rate_league.py --freeze-policy artifacts/mixed-pilot-rating-policy.json

# Uses the local private schedule and aggregate audited game reports; no inference.
python scripts/rate_league.py
```

The CLI requires its policy file to match the versioned policy, verifies the
gameplay preregistration and independently audits the local raw evidence for
every completed game used in the fit. It writes
`artifacts/mixed-pilot-ratings.json`, including configuration/role ratings,
intervals, valid/excluded game IDs, the declared priors and an input digest.
After additional games, refit from all results. Never merge role data across
changed prompts/models under the same configuration ID. Unknown and duplicate
results or inconsistent paired layouts are rejected.

Synthetic tests cover a known skill difference, faction-only advantages,
empty-data uncertainty, failure exclusion, permutation/name invariance,
duplicate rejection and numerical solving. Calibration on held-out games,
prior sensitivity, seat-position effects, nonlinear teammate interactions and
long-term skill drift remain future work.
