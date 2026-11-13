"""Wait for the eighteen-game comparison, then run six fixed counterbalanced games."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.codex_quartet import ENTRIES, schedule, validate_schedule, configs_for
from werewolf.ratings import POLICY, fit_ratings
from scripts.extend_codex_quartet import fingerprint as prior_fingerprint, baseline_evidence, BASELINE, verify_plan as verify_prior
from scripts.play_codex import play, save
from scripts.play_codex_league import check_canaries, collect_existing, verify_trial
from scripts.play_league import scheduled_games
from scripts.run_logging import emit
from scripts.verify_codex import require

DEFAULT_PLAN = Path('artifacts/codex-quartet-21000/plan.private.json')
PRIOR = Path('artifacts/codex-quartet-extension-v1/plan.private.json')
VERSION = 'codex-quartet-queued-six-v1'


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint():
    return hashlib.sha256((prior_fingerprint()+Path(__file__).read_text()).encode()).hexdigest()


def next_schedule():
    entries = list(ENTRIES); matches = schedule(21000)
    mapping = {e: entries[(i+3)%4] for i,e in enumerate(entries)}
    for m in matches:
        m['entries'] = [mapping[e] for e in m['entries']]
    validate_schedule(matches)
    for m in matches:
        m['pair'] = f"21000:{m['pair']}"
    return matches


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_plan(path):
    require(not path.exists(), 'Do not overwrite the queued plan.')
    matches = next_schedule()
    prior = json.loads(PRIOR.read_text());verify_prior(prior, execution=True)
    plan = {'protocol': VERSION, 'source_fingerprint': fingerprint(), 'matches': matches,
            'configs': {m['id']: [asdict(c) for c in configs_for(m)] for m in matches},
            'previous_plan_hashes': {str(p): digest(p) for p in (BASELINE, PRIOR)},
            'canary_digests': check_canaries(path.parent, ENTRIES), 'rating_policy': POLICY,
            'workers_per_game': 2, 'max_batches': 300, 'parallel_games': 2,
            'start_policy': 'Wait for all twelve prior extension games to finish successfully and all eighteen prior games to pass offline replay; otherwise do not start.',
            'failure_policy': 'Retain attempts, stop new launches on failure, collect in-flight games; no replacements or fallback actions.'}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2);stream.write('\n')
    save(path.parent/'preregistration.json', {k:v for k,v in plan.items() if k not in ('matches','configs')}
         | {'additional_games':6, 'cumulative_planned_games':24, 'cohort_seed':21000, 'category_rotation':3,
            'entries': {e:{'model':m,'effort':f} for e,(m,f) in ENTRIES.items()},
            'cumulative_role_exposure_per_entry': {'wolf':24,'villager':24,'seer':6,'witch':6,'hunter':6,'idiot':6},
            'schedule_digest': hashlib.sha256(json.dumps(matches,sort_keys=True).encode()).hexdigest()})
    return plan


def verify(plan, execution=False):
    require(plan['protocol']==VERSION and plan['matches']==next_schedule(), 'Queued schedule changed.')
    require(plan['configs']=={m['id']:[asdict(c) for c in configs_for(m)] for m in plan['matches']}, 'Fixed configurations changed.')
    require(plan['rating_policy']==POLICY and (plan['workers_per_game'],plan['max_batches'],plan['parallel_games'])==(2,300,2), 'Policy changed.')
    require(plan['previous_plan_hashes']=={str(p):digest(p) for p in (BASELINE,PRIOR)}, 'Previous plans changed.')
    if execution:
        require(plan['source_fingerprint']==fingerprint(), 'Code changed since queue preregistration.')


def prior_ready(status):
    if status.get('phase') in ('stopped_on_failure','host_error','stopped_before_all_games_returned'):
        raise ValueError('Previous run stopped unsuccessfully; queued games will not start.')
    if status.get('phase')!='finished':
        return False
    require(status.get('completed_games')==12 and status.get('returned_games')==12
            and status.get('runner_exit_code')==0 and status.get('rating_exit_code')==0,
            'Previous run did not complete all twelve games successfully.')
    return True


def previous_evidence(plan):
    old, reports, hashes = baseline_evidence(BASELINE)
    prior = json.loads(PRIOR.read_text());verify_prior(prior)
    require(hashes==prior['baseline_hashes'], 'Original baseline changed.')
    extension, remaining = collect_existing(prior, PRIOR.parent)
    require(not remaining and len(extension)==12 and all(r['all_checks_passed'] for r in extension), 'Prior extension failed re-audit.')
    hashes.update({str(p):digest(p) for p in [PRIOR, PRIOR.parent/'results.json']+
                   [PRIOR.parent/f"{m['id']}.private.json" for m in prior['matches']]})
    return old+prior['matches'], reports+extension, hashes


def run_one(match,plan,root):
    verify(plan,execution=True);stem=match['id']
    require(not any((root/f'{stem}{s}').exists() for s in ('.json','.private.json')), 'Do not overwrite paid evidence.')
    with (root/f'{stem}.claim.private.json').open('x') as stream:json.dump({'match_id':stem},stream)
    try:
        play(match['seed'],configs=configs_for(match),roles=match['roles'],artifact_stem=stem,output_dir=root,
             workers=plan['workers_per_game'],max_batches=plan['max_batches'])
        report=verify_trial(json.loads((root/f'{stem}.private.json').read_text()),match,plan)
    except Exception as error:
        report={'status':'host_or_audit_error','all_checks_passed':False,
                'category':getattr(error,'validation_details',{}).get('category',type(error).__name__)}
    report.update(match_id=stem,pair=match['pair'],seed=match['seed']);save(root/f'{stem}.json',report)
    return report


def write_results(plan,root,reports,halted,baseline):
    old,previous,hashes=baseline
    save(root/'results.json',{'reports':sorted(reports,key=lambda r:r['match_id']),
         'scheduler':{'scheduled_games':6,'returned_games':len(reports),'halted_on_failure':halted,
                      'unattempted':[m['id'] for m in plan['matches'] if m['id'] not in {r['match_id'] for r in reports}]}})
    save(root/'ratings.json',fit_ratings(plan['matches'],reports))
    cumulative=fit_ratings(old+plan['matches'],previous+reports);cumulative['baseline_hashes']=hashes
    save(root/'cumulative-ratings.json',cumulative)


def worker(path):
    root=path.parent;plan=json.loads(path.read_text());state={'pid':os.getpid()}
    status_path=root/'verification-status.private.json'
    try:
        with (root/'worker-lock.private.json').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            verify(plan,execution=True)
            while True:
                status=json.loads((PRIOR.parent/'verification-status.private.json').read_text())
                if prior_ready(status):break
                state.update(phase='waiting_for_previous',at_utc=now());save(status_path,state)
                # The detached worker owns this wait; no interactive tool is blocked.
                try:os.kill(status['pid'],0)
                except ProcessLookupError:
                    if prior_ready(json.loads((PRIOR.parent/'verification-status.private.json').read_text())):break
                    raise ValueError('Previous supervisor exited without a final status.') from None
                time.sleep(30)
            verify(plan,execution=True)
            require(check_canaries(root,ENTRIES)==plan['canary_digests'],'Canary evidence changed.')
            baseline=previous_evidence(plan)
            frozen=root/'baseline-evidence.private.json'
            if frozen.exists():require(json.loads(frozen.read_text())==baseline[2],'Previous evidence changed since this batch started.')
            else:save(frozen,baseline[2])
            state.update(phase='running_games',at_utc=now());save(status_path,state)
            reports,remaining=collect_existing(plan,root);halted=any(not r['all_checks_passed'] for r in reports)
            write_results(plan,root,reports,halted,baseline)
            if not halted:
                for report,halted in scheduled_games(remaining,lambda m:run_one(m,plan,root),parallel_games=2):
                    reports.append(report);write_results(plan,root,reports,halted,baseline)
                    state.update(returned_games=len(reports),completed_games=sum(bool(r['all_checks_passed']) for r in reports),at_utc=now());save(status_path,state)
                    emit({'match_id':report['match_id'],'status':report['status'],'all_checks_passed':report['all_checks_passed']})
            state.update(phase='finished' if len(reports)==6 and not halted else 'stopped_on_failure',
                         returned_games=len(reports),completed_games=sum(bool(r['all_checks_passed']) for r in reports))
    except Exception as error:
        state.update(phase='host_error',category=type(error).__name__)
    finally:
        state['at_utc']=now();save(status_path,state)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=DEFAULT_PLAN)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create-plan',action='store_true');group.add_argument('--launch',action='store_true');group.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    if args.create_plan:create_plan(args.plan);emit({'additional_games':6,'queued_after':str(PRIOR)});return
    if args.worker:worker(args.plan);return
    require(args.plan.exists(),'Create the queue plan first.')
    with (args.plan.parent/'verification-process.private.json').open('x') as marker:
        with (args.plan.parent/'verification.log').open('x') as log:
            child=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--worker','--plan',str(args.plan.resolve())],
                cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        json.dump({'pid':child.pid,'plan':str(args.plan),'created_at_utc':now()},marker)
    emit({'queued_pid':child.pid,'plan':str(args.plan)})


if __name__=='__main__':main()
