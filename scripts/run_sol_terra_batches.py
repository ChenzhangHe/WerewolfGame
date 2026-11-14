"""Run declared six-game Sol/Terra cohorts sequentially, six games at a time."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf.codex_league import schedule, configs_for, selected_entries
from scripts.play_codex import save
from scripts.play_codex_league import fingerprint as league_fingerprint, create_plan, verify_plan, collect_existing, write_results
from scripts.export_replays import export
from scripts.rate_replays import calculate
from scripts.run_logging import emit
from scripts.verify_codex import require

VERSION = 'sol-terra-multi-batch-v1'
DEFAULT_PLAN = Path('artifacts/codex-sol-terra-more-v1/plan.private.json')


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint():
    return hashlib.sha256((league_fingerprint()+Path(__file__).read_text()).encode()).hexdigest()


def batches(seed, count):
    if type(seed) is not int or seed < 0 or type(count) is not int or not 1 <= count <= 4:
        raise ValueError('Declare one to four six-game cohorts.')
    result=[]
    for i in range(count):
        current=seed+1000*i;matches=schedule(current,profile='sol-terra')
        result.append({'seed':current,'root':f'artifacts/codex-sol-terra-{current}', 'matches':matches,
                       'configs':{m['id']:[asdict(c) for c in configs_for(m)] for m in matches}})
    return result


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_campaign(path, seed=27000, count=2):
    require(not path.exists(),'Do not overwrite a campaign.')
    cohorts=batches(seed,count)
    for cohort in cohorts:
        require(not Path(cohort['root']).exists(),'An intended cohort directory already exists.')
    baseline={p.name:file_hash(p) for p in sorted(Path('replays').glob('*.json'))}
    plan={'protocol':VERSION,'source_fingerprint':fingerprint(),'start_seed':seed,'cohort_count':count,
          'cohorts':cohorts,'baseline_replays':baseline,'parallel_games':6,
          'entries':{e:{'model':m,'effort':f} for e,(m,f) in selected_entries('sol-terra').items()},
          'failure_policy':'Stop new cohorts on failure; collect in-flight games; retain interrupted attempts and never recreate uncertain seat threads.',
          'scoring_policy':'Retain every valid historical outcome once; pooled Sol/Terra model-family ratings with disclosed historical effort differences.'}
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(plan,stream,ensure_ascii=False,indent=2);stream.write('\n')
    save(path.parent/'preregistration.json',{k:v for k,v in plan.items() if k!='cohorts'} |
         {'additional_games':6*count,'cohort_seeds':[c['seed'] for c in cohorts],
          'schedule_digest':hashlib.sha256(json.dumps(cohorts,sort_keys=True).encode()).hexdigest()})
    return plan


def verify(plan):
    require(plan['protocol']==VERSION and plan['cohorts']==batches(plan['start_seed'],plan['cohort_count']), 'Campaign schedule changed.')
    require(plan['parallel_games']==6 and plan['source_fingerprint']==fingerprint(), 'Execution source or concurrency changed.')
    require(plan['entries']=={e:{'model':m,'effort':f} for e,(m,f) in selected_entries('sol-terra').items()},'Fixed model settings changed.')
    for name,value in plan['baseline_replays'].items():
        require(Path(name).name==name and file_hash(Path('replays')/name)==value,'Baseline replay changed.')


def batch_succeeded(exit_code, reports):
    return exit_code==0 and len(reports)==6 and all(r.get('all_checks_passed') for r in reports)


def worker(path):
    plan=json.loads(path.read_text());root=path.parent
    state={'pid':os.getpid(),'phase':'validating','completed_new_games':0,'returned_new_games':0,'planned_new_games':6*plan['cohort_count']}
    status=root/'verification-status.private.json';expected=set(plan['baseline_replays']);new_reports=[]
    try:
        with (root/'worker-lock.private.json').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            verify(plan);save(status,state|{'at_utc':now()})
            save(root/'ratings.json',calculate(Path('replays'),grouping='model-family'))
            for cohort in plan['cohorts']:
                verify(plan)
                require({p.name for p in Path('replays').glob('*.json')}==expected,'Unexpected replay additions would change the declared history.')
                destination=Path(cohort['root']);destination.mkdir(exist_ok=False)
                for name in ('Sol','Terra'):
                    for suffix in ('.json','.private.json'):
                        shutil.copyfile(Path('artifacts/codex-sol-terra-26000')/f'canary-{name}{suffix}',destination/f'canary-{name}{suffix}')
                batch_plan=create_plan(destination/'plan.private.json',cohort['seed'],profile='sol-terra',parallel_games=6)
                require(batch_plan['matches']==cohort['matches'] and batch_plan['configs']==cohort['configs'],'Cohort differs from the campaign declaration.')
                verify_plan(batch_plan,execution=True)
                process=subprocess.Popen([sys.executable,'-u','scripts/play_codex_league.py','--plan',str(destination/'plan.private.json'),'--run'])
                state.update(phase='running_games',cohort_seed=cohort['seed'],worker_pid=process.pid)
                while process.poll() is None:
                    ledger=destination/'results.json'
                    current=json.loads(ledger.read_text())['reports'] if ledger.exists() else []
                    state.update(at_utc=now(),completed_new_games=sum(bool(r.get('all_checks_passed')) for r in new_reports+current),
                                 returned_new_games=len(new_reports)+len(current))
                    save(status,state)
                    rating_path=destination/'ratings.json'
                    if rating_path.exists():save(root/'ratings.json',json.loads(rating_path.read_text()))
                    time.sleep(10)
                reports,remaining=collect_existing(batch_plan,destination)
                success=batch_succeeded(process.returncode,reports)
                write_results(batch_plan,destination,reports,not success)
                save(destination/'verification-status.private.json',{'phase':'finished' if success else 'stopped_on_failure',
                     'runner_exit_code':process.returncode,'completed_games':sum(bool(r.get('all_checks_passed')) for r in reports),
                     'returned_games':len(reports),'at_utc':now()})
                for report in reports:
                    if report.get('all_checks_passed'):
                        source=destination/(report['match_id']+'.private.json');target=Path('replays')/(report['match_id']+'.json')
                        require(not target.exists(),'Do not overwrite published gameplay.')
                        export(source,Path('replays'));expected.add(target.name)
                new_reports.extend(reports)
                save(root/'results.json',{'reports':new_reports,'planned_new_games':6*plan['cohort_count']})
                save(root/'ratings.json',json.loads((destination/'ratings.json').read_text()))
                state.update(at_utc=now(),completed_new_games=sum(bool(r.get('all_checks_passed')) for r in new_reports),
                             returned_new_games=len(new_reports),last_worker_exit_code=process.returncode)
                emit({'cohort':cohort['seed'],'successful':success,'completed_new_games':state['completed_new_games']})
                if not success:
                    state['phase']='stopped_on_failure';save(status,state);return
            state['phase']='finished'
    except Exception as error:
        state.update(phase='host_error',category=type(error).__name__,frames=[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(error.__traceback__)[-6:]])
    finally:
        state['at_utc']=now();save(status,state)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=DEFAULT_PLAN)
    parser.add_argument('--seed',type=int,default=27000);parser.add_argument('--batches',type=int,default=2)
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--create-plan',action='store_true');actions.add_argument('--launch',action='store_true');actions.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    if args.create_plan:create_campaign(args.plan,args.seed,args.batches);emit({'additional_games':6*args.batches,'plan':str(args.plan)});return
    if args.worker:worker(args.plan);return
    require(args.plan.exists(),'Create the campaign plan first.')
    with (args.plan.parent/'verification-process.private.json').open('x') as marker:
        with (args.plan.parent/'verification.log').open('x') as log:
            process=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--worker','--plan',str(args.plan.resolve())],
                cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        json.dump({'pid':process.pid,'plan':str(args.plan),'created_at_utc':now()},marker)
    emit({'detached_pid':process.pid,'new_games':json.loads(args.plan.read_text())['cohort_count']*6})


if __name__=='__main__':main()
