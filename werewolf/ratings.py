"""Elo-scale, role-aware team ratings from one binary result per game.

A regularized Bradley–Terry model with configuration effects, shrunk role
adjustments, a Good-side baseline and shared-layout random intercepts. Fits a
MAP and Laplace approximation; it is not traditional fixed-K online Elo.
"""
from collections import Counter
import hashlib
import json
import math

VERSION = 'hierarchical-team-elo-v1'
ROLES = ('wolf', 'villager', 'seer', 'witch', 'hunter', 'idiot')
ROLE_COUNTS = Counter(wolf=4, villager=4, seer=1, witch=1, hunter=1, idiot=1)
WEIGHTS = dict(wolf=.5, villager=.25, seer=.0625, witch=.0625, hunter=.0625, idiot=.0625)
POLICY = {'version': VERSION, 'initial_rating': 1500, 'elo_scale': 400,
          'configuration_prior_sd': 200, 'role_adjustment_prior_sd': 100,
          'good_baseline_logit_prior_sd': 1, 'layout_logit_prior_sd': .5,
          'role_weights': WEIGHTS, 'outcome_unit': 'one-result-per-game',
          'inference': 'MAP-with-Laplace-approximation', 'failure_policy': 'retain-but-exclude-from-skill-fit'}


def sigmoid(value):
    if value >= 0:
        return 1/(1+math.exp(-value))
    z = math.exp(value)
    return z/(1+z)


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cholesky(matrix):
    size = len(matrix)
    lower = [[0.]*size for _ in range(size)]
    for i in range(size):
        for j in range(i+1):
            residual = matrix[i][j]-sum(lower[i][k]*lower[j][k] for k in range(j))
            if i == j:
                if residual <= 0 or not math.isfinite(residual):
                    raise ArithmeticError('Rating Hessian is not positive definite.')
                lower[i][j] = math.sqrt(residual)
            else:
                lower[i][j] = residual/lower[j][j]
    return lower


def solve(lower, vector):
    size = len(vector)
    forward, result = [0.]*size, [0.]*size
    for i in range(size):
        forward[i] = (vector[i]-sum(lower[i][j]*forward[j] for j in range(i)))/lower[i][i]
    for i in reversed(range(size)):
        result[i] = (forward[i]-sum(lower[j][i]*result[j] for j in range(i+1, size)))/lower[i][i]
    return result


def fit_ratings(matches, reports):
    """Refit all valid outcomes deterministically; failures never become defeats."""
    matches = sorted(matches, key=lambda m: m['id'])
    if len({m['id'] for m in matches}) != len(matches):
        raise ValueError('Duplicate game IDs would count outcomes twice.')
    entries = sorted({e for m in matches for e in m['entries']})
    if len(entries) < 2 or any(not isinstance(e, str) or not e for e in entries):
        raise ValueError('At least two configuration IDs are required.')
    for match in matches:
        if len(match['entries']) != 12 or Counter(match['roles']) != ROLE_COUNTS:
            raise ValueError('Ratings require the twelve-seat ruleset.')
    by_id = {r['match_id']: r for r in reports}
    if len(by_id) != len(reports) or set(by_id)-{m['id'] for m in matches}:
        raise ValueError('Duplicate or unknown game result.')
    valid, excluded = [], []
    for match in matches:
        report = by_id.get(match['id'])
        if not report or not report.get('all_checks_passed'):
            excluded.append({'match_id': match['id'], 'status': report.get('status', 'failed') if report else 'unattempted'})
        elif report.get('winner') not in ('good', 'wolves'):
            raise ValueError('An audited result must have a valid winner.')
        else:
            valid.append((match, int(report['winner'] == 'good')))
    pair_key = lambda m: str(m.get('pair', m['id']))
    pairs = sorted({pair_key(m) for m in matches})
    layouts = {}
    for match in matches:
        key = pair_key(match)
        if key in layouts and layouts[key] != match['roles']:
            raise ValueError('A paired layout group has different role layouts.')
        layouts[key] = match['roles']
    names = [('baseline',)] + [('configuration', e) for e in entries]
    names += [('role', e, role) for e in entries for role in ROLES]
    names += [('layout', pair) for pair in pairs]
    indices = {key: i for i, key in enumerate(names)}
    size = len(names)
    scale = math.log(10)/POLICY['elo_scale']
    mu_sd, role_sd = POLICY['configuration_prior_sd'], POLICY['role_adjustment_prior_sd']

    def features(match):
        vector = [0.]*size
        vector[0] = POLICY['good_baseline_logit_prior_sd']
        counts = {e: {r: 0. for r in ROLES} for e in entries}
        for entry, role in zip(match['entries'], match['roles']):
            counts[entry][role] += -1/4 if role == 'wolf' else 1/8
        for entry in entries:
            vector[indices['configuration', entry]] = scale*mu_sd*sum(counts[entry].values())
            for role in ROLES:
                # Common role offsets cannot masquerade as a faction advantage.
                centered = counts[entry][role]-sum(counts[e][role] for e in entries)/len(entries)
                vector[indices['role', entry, role]] = scale*role_sd*centered
        vector[indices['layout', pair_key(match)]] = POLICY['layout_logit_prior_sd']
        return vector

    data = [(features(match), outcome) for match, outcome in valid]

    def loss(theta):
        total = .5*dot(theta, theta)
        for vector, outcome in data:
            z = dot(theta, vector)
            total += max(z, 0)+math.log1p(math.exp(-abs(z)))-outcome*z
        return total

    def derivatives(theta):
        gradient = theta[:]
        hessian = [[float(i == j) for j in range(size)] for i in range(size)]
        for vector, outcome in data:
            probability = sigmoid(dot(theta, vector))
            variance = probability*(1-probability)
            for i, value in enumerate(vector):
                gradient[i] += (probability-outcome)*value
                for j in range(i+1):
                    update = variance*value*vector[j]
                    hessian[i][j] += update
                    if i != j:
                        hessian[j][i] += update
        return gradient, hessian

    theta, iterations = [0.]*size, 0
    for iterations in range(65):
        gradient, hessian = derivatives(theta)
        if max(map(abs, gradient), default=0.) < 1e-8:
            break
        direction = solve(cholesky(hessian), gradient)
        previous, step = loss(theta), 1.
        for _ in range(32):
            candidate = [t-step*d for t, d in zip(theta, direction)]
            if loss(candidate) <= previous-1e-4*step*dot(gradient, direction):
                theta = candidate
                break
            step *= .5
        else:
            raise ArithmeticError('Rating optimizer line search failed.')
    else:
        raise ArithmeticError('Rating optimizer did not converge.')
    _, hessian = derivatives(theta)
    lower = cholesky(hessian)

    def estimate(vector, base=1500):
        mean = base+dot(vector, theta)
        sd = math.sqrt(max(0., dot(vector, solve(lower, vector))))
        return {'rating': round(mean, 2), 'sd': round(sd, 2),
                'approx_95_interval': [round(mean-1.96*sd, 2), round(mean+1.96*sd, 2)]}

    def role_vector(entry, role):
        vector = [0.]*size
        vector[indices['configuration', entry]] = mu_sd
        for other in entries:
            vector[indices['role', other, role]] = role_sd*((entry == other)-1/len(entries))
        return vector

    appearances = {entry: Counter() for entry in entries}
    for match, _ in valid:
        for entry, role in zip(match['entries'], match['roles']):
            appearances[entry][role] += 1
    rows, overall_vectors = [], {}
    for entry in entries:
        roles = {role: role_vector(entry, role) for role in ROLES}
        overall = [sum(WEIGHTS[role]*roles[role][i] for role in ROLES) for i in range(size)]
        overall_vectors[entry] = overall
        shared = [0.]*size
        shared[indices['configuration', entry]] = mu_sd
        rows.append({'entry': entry, **estimate(overall), 'shared_component': estimate(shared),
                     'roles': {r: {**estimate(v), 'appearances': appearances[entry][r]} for r, v in roles.items()},
                     'seat_appearances': sum(appearances[entry].values())})
    comparisons = []
    for i, entry in enumerate(entries):
        for other in entries[i+1:]:
            diff = [a-b for a, b in zip(overall_vectors[entry], overall_vectors[other])]
            mean = dot(diff, theta)
            sd = math.sqrt(dot(diff, solve(lower, diff)))
            comparisons.append({'a': entry, 'b': other, 'difference': estimate(diff, base=0),
                                'approx_probability_a_stronger': .5*(1+math.erf(mean/sd/math.sqrt(2)))})
    fingerprint = hashlib.sha256(json.dumps({'matches': matches, 'reports': sorted(reports, key=lambda r: r['match_id'])},
                                            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'version': VERSION, 'policy': POLICY, 'valid_games': len(valid), 'scheduled_games': len(matches),
            'excluded': excluded, 'source_digest': fingerprint, 'iterations': iterations, 'converged': True,
            'ratings': sorted(rows, key=lambda row: (-row['rating'], row['entry'])), 'comparisons': comparisons,
            'good_baseline_probability_at_map': sigmoid(theta[0]*POLICY['good_baseline_logit_prior_sd']),
            'in_sample_probabilities': [{'match_id': m['id'], 'good_win_probability_at_map': sigmoid(dot(features(m), theta))}
                                        for m, _ in valid],
            'status': 'exploratory-not-a-calibrated-leaderboard',
            'uncertainty': 'Marginal Laplace approximation with fixed priors, not MCMC or empirical confidence intervals.'}
