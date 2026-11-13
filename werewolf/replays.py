"""Portable complete gameplay replays. No model requests, notes or credentials."""
from copy import deepcopy
from pathlib import Path
import json
import re

from .engine import Game

FORMAT = 'werewolf-replay-v1'
REPLAY_ROOT = Path(__file__).resolve().parents[1]/'replays'
CONFIG_FIELDS = {'seat', 'name', 'provider', 'model', 'reasoning_effort', 'personality', 'language', 'interaction_mode', 'entry'}
ACTION_FIELDS = {'type', 'target', 'value', 'text'}


class ReplayRunner:
    read_only = True
    allow_format_repair = False

    def __init__(self, archive):
        try:
            self._load(archive)
        except (KeyError, TypeError, AttributeError, IndexError, ValueError):
            raise ValueError('Invalid or inconsistent gameplay replay.') from None

    def _load(self, archive):
        if not isinstance(archive, dict) or set(archive) != {'format', 'ruleset', 'id', 'title', 'language', 'seed', 'roles', 'configs', 'batches', 'layout_group', 'source_digest'}:
            raise ValueError('Unexpected replay fields.')
        if archive['format'] != FORMAT or archive['ruleset'] != 'rules-v1' or archive['language'] not in ('en', 'zh'):
            raise ValueError('Unknown replay format.')
        if not isinstance(archive['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', archive['id']):
            raise ValueError('Invalid replay ID.')
        if not isinstance(archive['title'], str) or not 1 <= len(archive['title']) <= 150:
            raise ValueError('Invalid replay title.')
        if type(archive['seed']) is not int or not 0 <= archive['seed'] <= 2**53-1:
            raise ValueError('Invalid seed.')
        if not isinstance(archive['layout_group'], str) or len(archive['layout_group']) > 100 or not isinstance(archive['source_digest'], str) or not re.fullmatch('[a-f0-9]{64}', archive['source_digest']):
            raise ValueError('Invalid replay provenance.')
        configs = archive['configs']
        if not isinstance(configs, list) or len(configs) != 12:
            raise ValueError('Twelve configurations required.')
        for seat, c in enumerate(configs, 1):
            if not isinstance(c, dict) or set(c) != CONFIG_FIELDS or type(c['seat']) is not int or c['seat'] != seat:
                raise ValueError('Invalid fixed configuration.')
            if any(not isinstance(c[k], str) or len(c[k]) > (2000 if k == 'personality' else 150) for k in CONFIG_FIELDS-{'seat'}):
                raise ValueError('Invalid configuration text.')
            if not c['name'] or not c['model'] or not c['entry'] or c['language'] != archive['language']:
                raise ValueError('Invalid configuration identity.')
        if not isinstance(archive['batches'], list) or not 1 <= len(archive['batches']) <= 300:
            raise ValueError('Invalid batch count.')
        self.archive = deepcopy(archive)
        self.language = archive['language']
        self.game = Game(seed=archive['seed'], names=[c['name'] for c in configs], roles=archive['roles'], language=self.language)
        self._checkpoints = []
        self._capture()
        for batch in archive['batches']:
            pending = self.game.pending()
            if not isinstance(batch, list) or len(batch) != len(pending):
                raise ValueError('Incomplete decision batch.')
            expected = {d['seat']: d for d in pending}; actions = {}; seen = set()
            for row in batch:
                if not isinstance(row, dict) or set(row) != {'seat', 'kind', 'action'} or type(row['seat']) is not int:
                    raise ValueError('Unexpected decision fields.')
                d = expected[row['seat']]
                if row['seat'] in seen or row['kind'] != d['kind'] or not isinstance(row['action'], dict) or set(row['action'])-ACTION_FIELDS:
                    raise ValueError('Invalid decision provenance.')
                seen.add(row['seat']); actions[d['id']] = row['action']
            self.game.submit(actions)
            self._capture()
        if not self.game.winner:
            raise ValueError('Only completed games belong in this replay library.')
        self.status = 'finished'; self.error = None

    def _capture(self):
        self._checkpoints.append({'mystery': self.game.view('mystery'), 'omniscient': self.game.view('omniscient'),
                                  **{f'player:{s}': self.game.view('player', s) for s in range(1, 13)}})

    @property
    def max_step(self):
        return len(self._checkpoints)-1

    def replay(self, index, mode='mystery', seat=None):
        if type(index) is not int or not 0 <= index <= self.max_step or mode not in ('mystery', 'omniscient', 'player'):
            raise ValueError('Invalid replay perspective or checkpoint.')
        if mode == 'player' and (type(seat) is not int or not 1 <= seat <= 12):
            raise ValueError('Invalid followed seat.')
        result = deepcopy(self._checkpoints[index][f'player:{seat}' if mode == 'player' else mode])
        result.update(step=index, max_step=self.max_step, configs=deepcopy(self.archive['configs']),
                      status='finished' if result['winner'] else 'paused', error=None, read_only=True,
                      replay_id=self.archive['id'], replay_title=self.archive['title'], allow_format_repair=False)
        return result

    def snapshot(self, mode='mystery', seat=None):
        return self.replay(self.max_step, mode, seat)

    def step(self):
        raise ValueError('Saved games are read-only; use the replay timeline.')

    def export(self):
        return deepcopy(self.archive)


def library(root=REPLAY_ROOT):
    rows = []
    for p in sorted(root.glob('*.json')):
        d = json.loads(p.read_text())
        if d.get('format') == FORMAT and d.get('id') == p.stem:
            rows.append({'id': d['id'], 'title': d['title'], 'language': d['language'], 'steps': len(d['batches'])})
    return rows


def load_replay(identifier, root=REPLAY_ROOT):
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier):
        raise ValueError('Invalid replay ID.')
    path = root/f'{identifier}.json'
    if not path.is_file() or path.is_symlink():
        raise ValueError('Replay not found.')
    return ReplayRunner(json.loads(path.read_text()))
