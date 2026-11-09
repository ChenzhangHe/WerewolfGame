"""Trusted twelve-player referee; provider code receives only observe() output."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import random
import uuid

ROLES = ['wolf'] * 4 + ['villager'] * 4 + ['seer', 'witch', 'hunter', 'idiot']
ROLE_COUNTS = dict(Counter(ROLES))
SPEECH_LIMIT = 1200


class Game:
    """A game advances only when a complete, validated decision batch is submitted.

    Internal decision IDs are random routing tokens, never part of a model input.
    Public and private views are freshly projected copies, not shared references.
    """

    def __init__(self, seed=1, names=None, roles=None, language="en"):
        if language not in ("en", "zh"):
            raise ValueError("Language must be en or zh.")
        self.language = language
        self.seed = seed
        assigned = list(ROLES if roles is None else roles)
        if Counter(assigned) != Counter(ROLES):
            raise ValueError('Expected the standard twelve-role lineup.')
        if roles is None:
            random.Random(seed).shuffle(assigned)
        if names is not None and (len(names) != 12 or any(not isinstance(n, str) for n in names)):
            raise ValueError('Expected twelve player names.')
        self.players = {s: {'seat': s, 'name': (names or [f'Player {i}' for i in range(1, 13)])[s-1],
                            'role': assigned[s-1], 'alive': True, 'revealed_role': None}
                        for s in range(1, 13)}
        # Independent randomness stream: hidden role shuffle never consumes order RNG.
        self._order_rng = random.Random(f'order:{seed}')
        self.day = 1
        self.phase = 'night'
        self.winner = None
        self.sheriff = None
        self.events = []
        self.antidote = True
        self.poison = True
        self.idiot_revealed = False
        self._attack = None
        self._poison_target = None
        self._pending_deaths = []
        self._night_deaths = []
        self._night_start = []
        self._election_done = False
        self._election_candidates = []
        self._election_original = []
        self._election_voters = []
        self._election_explosions = 0
        self._pending = []
        self._submitted = []
        self._event('setup', 'Twelve seats. Four Wolves, four Villagers, Seer, Witch, Hunter, and Idiot. Roles stay hidden on death.',
                    data={'ruleset': 'rules-v1', 'role_counts': ROLE_COUNTS})
        self._flow = self._run()
        self._advance()

    def _event(self, kind, text, *, seat=None, data=None, audience='public'):
        event = {'kind': kind, 'day': self.day, 'phase': self.phase,
                 'text': self._translate(kind, text, seat, data) if self.language == 'zh' else text, 'audience': audience}
        if seat is not None:
            event['seat'] = seat
        if data is not None:
            event['data'] = deepcopy(data)
        self.events.append(event)

    def _translate(self, kind, text, seat, data):
        """Localize referee messages only; never rewrite attributed player speech."""
        d = data or {}
        join = lambda values: '、'.join(map(str, values)) or '无'
        if kind in ('campaign', 'speech', 'tie_speech', 'last_words', 'wolf_discussion'):
            return text
        if kind == 'setup':
            return '十二人预女猎白：四狼、四民、预言家、女巫、猎人、白痴。出局不翻牌。'
        if kind == 'night':
            return f'第{self.day}夜，天黑请闭眼。'
        if kind == 'wolf_attack':
            return f'狼队选择袭击{d["target"]}号。' if d.get('target') else '狼队选择空刀。'
        if kind == 'witch_target':
            return f'今晚刀口是{d["target"]}号。' if d.get('target') else '今晚没有刀口。'
        if kind == 'witch_action':
            return '女巫选择' + {'pass': '不用药。', 'save': '使用解药。', 'poison': f'对{d.get("target")}号使用毒药。'}[d['type']]
        if kind == 'investigation':
            return f'{d["target"]}号的查验结果是' + ('狼人。' if d['result'] == 'wolf' else '好人。')
        if kind == 'hunter_status':
            return '你可以在符合条件的死亡时开枪。' if d['can_shoot'] else '你已中毒，不能发动猎人开枪技能。'
        if kind == 'dawn':
            return f'天亮了，昨夜出局的是{join(d["deaths"])}号。' if d['deaths'] else '天亮了，昨夜是平安夜。'
        if kind == 'election':
            return '警长竞选开始，尚未公布昨夜死讯。' if not self._election_explosions else '恢复警长竞选，直接退水和投票，不重复竞选发言。'
        if kind == 'nominations':
            return f'上警玩家：{join(d["candidates"])}。'
        if kind == 'withdrawals':
            return f'仍在警上的玩家：{join(d["candidates"])}。'
        if kind == 'sheriff':
            return f'{d["sheriff"]}号当选警长。' if d.get('sheriff') else ('第二次警上自爆，警徽流失。' if self._election_explosions >= 2 else '本局没有警长。')
        if kind == 'speaking_order':
            return f'发言顺序：{join(d["order"])}。'
        if kind in ('sheriff_ballots', 'exile_ballots'):
            return '票型：' + '，'.join(f'{s}号投{t}号' if t is not None else f'{s}号弃票' for s, t in d['votes'].items()) + '。'
        if kind == 'no_exile':
            return '本轮无人被放逐。'
        if kind == 'exile':
            return f'{seat}号被放逐出局。'
        if kind == 'idiot_reveal':
            return f'{seat}号翻牌为白痴，免于出局，此后不能投票或被投票。'
        if kind == 'explosion':
            return f'{seat}号狼人自爆。'
        if kind == 'hunter_shot':
            return f'{seat}号猎人开枪带走{d["target"]}号。'
        if kind == 'hunter_declined':
            return '你选择不开枪。'
        if kind == 'badge':
            return f'警徽移交给{d["sheriff"]}号。' if d.get('sheriff') else '警徽被撕毁。'
        if kind == 'game_over':
            return ('好人阵营' if d['winner'] == 'good' else '狼人阵营') + '获胜！游戏结束，公布所有身份。'
        return text

    def _alive(self):
        return [s for s, p in self.players.items() if p['alive']]

    def _role(self, role, alive=True):
        return [s for s, p in self.players.items() if p['role'] == role and (p['alive'] or not alive)]

    def _decision(self, seat, kind, options):
        return {'id': uuid.uuid4().hex, 'seat': seat, 'kind': kind, 'options': options}

    def _ask(self, seats, kind, options):
        """Yield one batch and return actions indexed by seat."""
        decisions = [self._decision(s, kind, options(s) if callable(options) else deepcopy(options)) for s in seats]
        if not decisions:
            return {}
        result = yield decisions
        return {d['seat']: result[d['id']] for d in decisions}

    def _advance(self, actions=None):
        try:
            self._pending = next(self._flow) if actions is None else self._flow.send(actions)
        except StopIteration:
            self._pending = []

    def pending(self):
        return deepcopy(self._pending)

    def submit(self, actions):
        if not self._pending or not isinstance(actions, dict) or set(actions) != {d['id'] for d in self._pending}:
            raise ValueError('Submit exactly the current decision batch.')
        cleaned = {}
        for d in self._pending:
            action = actions[d['id']]
            if not isinstance(action, dict):
                raise ValueError('An action must be an object.')
            extra = set(action) - {'text', 'notes'}
            candidate = {k: action[k] for k in extra}
            # JSON booleans must not pass as numeric seat targets.
            if 'target' in candidate and candidate['target'] is not None and type(candidate['target']) is not int:
                raise ValueError('Invalid action target.')
            if candidate not in d['options']:
                raise ValueError('Action is not one of the legal options.')
            if ('text' in action and action.get('type') not in ('speak', 'discuss')):
                raise ValueError('Text is only accepted for a speech action.')
            if action.get('type') in ('speak', 'discuss') and (not isinstance(action.get('text'), str) or len(action['text']) > SPEECH_LIMIT):
                raise ValueError(f'Speech must be text with at most {SPEECH_LIMIT} characters.')
            if 'notes' in action and (not isinstance(action['notes'], str) or len(action['notes']) > 4000):
                raise ValueError('Invalid private notes.')
            cleaned[d['id']] = deepcopy(action)
        # Validation above performs no writes; all members saw the same pre-batch state.
        self._submitted.append({'decisions': deepcopy(self._pending), 'actions': deepcopy(cleaned)})
        self._advance(cleaned)

    def _project_events(self, seat=None, omniscient=False):
        result = []
        for original in self.events:
            audience = original['audience']
            if omniscient or audience == 'public' or (seat is not None and seat in audience):
                e = deepcopy(original)
                if not omniscient and audience != 'public':
                    e['audience'] = 'private'
                result.append(e)
        return result

    def _public_players(self, seat=None, omniscient=False):
        result = []
        for s, p in self.players.items():
            q = {k: deepcopy(p[k]) for k in ('seat', 'name', 'alive', 'revealed_role')}
            q['sheriff'] = s == self.sheriff
            if omniscient or self.winner or s == seat or p['revealed_role']:
                q['role'] = p['role']
            result.append(q)
        return result

    def observe(self, seat):
        if isinstance(seat, bool) or seat not in self.players:
            raise ValueError('Seat must be between 1 and 12.')
        role = self.players[seat]['role']
        result = {'seat': seat, 'role': role, 'day': self.day, 'phase': self.phase,
                  'ruleset': 'rules-v1', 'language': self.language, 'role_counts': deepcopy(ROLE_COUNTS),
                  'players': self._public_players(seat=seat), 'history': self._project_events(seat=seat),
                  'winner': self.winner}
        if role == 'wolf':
            result['wolf_teammates'] = self._role('wolf', alive=False)
        if role == 'witch':
            result['potions'] = {'antidote': self.antidote, 'poison': self.poison}
        return deepcopy(result)

    def view(self, mode='mystery', seat=None):
        if mode not in ('mystery', 'omniscient', 'player'):
            raise ValueError('Unknown perspective.')
        if mode == 'player' and (isinstance(seat, bool) or seat not in self.players):
            raise ValueError('Player perspective requires a valid seat.')
        player_seat = seat if mode == 'player' else None
        result = {'day': self.day, 'phase': self.phase, 'language': self.language, 'winner': self.winner,
                  'players': self._public_players(player_seat, mode == 'omniscient'),
                  'events': self._project_events(player_seat, mode == 'omniscient'),
                  'current_speakers': [d['seat'] for d in self._pending if d['kind'] in
                                       ('campaign', 'speech', 'tie_speech', 'last_words')]}
        if mode == 'player':
            result['observation'] = self.observe(seat)
        return deepcopy(result)

    def export(self):
        return deepcopy({'ruleset': 'rules-v1', 'language': self.language, 'seed': self.seed, 'players': list(self.players.values()),
                         'winner': self.winner, 'events': self.events, 'submitted_batches': self._submitted})

    def _winner_for(self, dead=()):
        living = [p for s, p in self.players.items() if p['alive'] and s not in dead]
        if not any(p['role'] == 'wolf' for p in living):
            return 'good'
        if not any(p['role'] == 'villager' for p in living) or not any(p['role'] not in ('wolf', 'villager') for p in living):
            return 'wolves'
        return None

    def _check_win(self):
        winner = self._winner_for()
        if winner:
            self.winner = winner
            self.phase = 'finished'
            self._event('game_over', f'{"Good" if winner == "good" else "Wolves"} win. All roles are revealed.',
                        data={'winner': winner, 'roles': {str(s): p['role'] for s, p in self.players.items()}})
        return bool(winner)

    def _run(self):
        while not self.winner:
            yield from self._night()
            self.phase = 'day'
            # An attack that already completes a win ends before election/inference.
            if self._attack is not None and self._winner_for([self._attack]):
                yield from self._announce_night()
                return
            if not self._election_done:
                interrupted = yield from self._election()
                if self.winner:
                    return
                if interrupted:
                    self.day += 1
                    continue
            yield from self._announce_night()
            if self.winner:
                return
            yield from self._discussion()
            if self.winner:
                return
            self.day += 1

    def _night(self):
        self.phase = 'night'
        self._event('night', f'Night {self.day}. Everyone closes their eyes.')
        self._night_start = self._alive()
        wolves = self._role('wolf')
        chats = yield from self._ask(wolves, 'wolf_discussion', [{'type': 'discuss'}])
        for s, a in chats.items():
            self._event('wolf_discussion', a['text'], seat=s, audience=wolves)
        votes = yield from self._ask(wolves, 'wolf_attack', [{'type': 'attack', 'target': t} for t in [None] + self._night_start])
        tally = Counter(a['target'] for a in votes.values() if a['target'] is not None)
        attack = min(tally, key=lambda t: (-tally[t], t)) if tally else None
        self._event('wolf_attack', f'Wolves choose {attack if attack else "no attack"}.',
                    data={'target': attack, 'ballots': {str(s): a['target'] for s, a in votes.items()}}, audience=wolves)
        self._poison_target = None
        witch = self._role('witch')
        if witch:
            w = witch[0]
            if self.antidote:
                self._event('witch_target', f'The wolf attack target is {attack if attack else "nobody"}.',
                            data={'target': attack}, audience=[w])
            options = [{'type': 'pass'}]
            if self.antidote and attack is not None and attack != w:
                options.append({'type': 'save'})
            if self.poison:
                options += [{'type': 'poison', 'target': s} for s in self._night_start]
            actions = yield from self._ask(witch, 'witch', options)
            a = actions[w]
            self._event('witch_action', f'Witch chooses {a["type"]}.', data=a, seat=w, audience=[w])
            if a['type'] == 'save':
                self.antidote = False
                attack = None
            elif a['type'] == 'poison':
                self.poison = False
                self._poison_target = a['target']
        seers = self._role('seer')
        if seers:
            s = seers[0]
            a = (yield from self._ask(seers, 'seer', [{'type': 'investigate', 'target': t} for t in self._night_start if t != s]))[s]
            result = 'wolf' if self.players[a['target']]['role'] == 'wolf' else 'good'
            self._event('investigation', f'Seat {a["target"]} is {result}.', seat=s,
                        data={'target': a['target'], 'result': result}, audience=[s])
        hunters = self._role('hunter')
        if hunters:
            h = hunters[0]
            self._event('hunter_status', 'You may shoot on eligible death.' if h != self._poison_target else 'Poison prevents your death shot.',
                        data={'can_shoot': h != self._poison_target}, audience=[h], seat=h)
        self._attack = attack
        self._pending_deaths = sorted(set(t for t in (attack, self._poison_target) if t is not None))

    def _announce_night(self):
        self.phase = 'day'
        deaths = [s for s in self._pending_deaths if self.players[s]['alive']]
        if self._attack is not None and self._winner_for([self._attack]):
            deaths = [self._attack] if self.players[self._attack]['alive'] else []
        self._night_deaths = list(deaths)
        self._event('dawn', 'Dawn. ' + ('Seats ' + ', '.join(map(str, deaths)) + ' died.' if deaths else 'Nobody died.'),
                    data={'deaths': deaths})
        # Attack precedence is evaluated before poison; mark all pending deaths
        # together before offering transfers/shots so no dead target is selectable.
        attack = self._attack
        if attack is not None and self.players[attack]['alive']:
            self.players[attack]['alive'] = False
            if self._check_win():
                return
        for s in deaths:
            self.players[s]['alive'] = False
        if self._check_win():
            return
        for s in deaths:
            if self.players[s]['role'] == 'hunter' and s != self._poison_target:
                yield from self._hunter(s, 'night')
                if self.winner:
                    return
        yield from self._badge_if_needed()
        if self.day == 1:
            for s in deaths:
                yield from self._speech(s, 'last_words')
        self._pending_deaths = []

    def _speech(self, seat, kind):
        a = (yield from self._ask([seat], kind, [{'type': 'speak'}]))[seat]
        self._event(kind, a['text'], seat=seat)

    def _explosion(self, election=False):
        wolves = self._role('wolf')
        choices = yield from self._ask(wolves, 'explosion', [{'type': 'pass'}, {'type': 'explode'}])
        explode = [s for s, a in choices.items() if a['type'] == 'explode']
        if not explode:
            return False
        seat = min(explode)
        self.players[seat]['alive'] = False
        self.players[seat]['revealed_role'] = 'wolf'
        self._event('explosion', f'Seat {seat} reveals as Wolf and self-explodes.', seat=seat)
        if election:
            self._election_explosions += 1
            if self._election_explosions >= 2:
                self._election_done = True
                self._event('sheriff', 'A second election explosion destroys the badge.', data={'sheriff': None})
        if not self._check_win():
            if election:
                yield from self._announce_night()
            else:
                yield from self._badge_if_needed()
        return True

    def _election(self):
        self.phase = 'election'
        if not self._election_explosions:
            self._event('election', 'Sheriff election begins before night deaths are announced.')
            nominations = yield from self._ask(self._alive(), 'nominate', [{'type': 'run'}, {'type': 'stay'}])
            self._election_original = [s for s, a in nominations.items() if a['type'] == 'run']
            self._election_candidates = list(self._election_original)
            self._election_voters = [s for s in self._alive() if s not in self._election_original]
            self._event('nominations', 'Sheriff candidates: ' + (', '.join(map(str, self._election_candidates)) or 'none') + '.',
                        data={'candidates': self._election_candidates})
            for s in self._election_candidates:
                if (yield from self._explosion(election=True)):
                    return True
                yield from self._speech(s, 'campaign')
        else:
            self._event('election', 'Sheriff election resumes with withdrawal and voting; no new campaign speeches.')
        candidates = [s for s in self._election_candidates if self.players[s]['alive']]
        choices = yield from self._ask(candidates, 'withdraw', [{'type': 'remain'}, {'type': 'withdraw'}])
        self._election_candidates = [s for s, a in choices.items() if a['type'] == 'remain']
        self._event('withdrawals', 'Remaining candidates: ' + (', '.join(map(str, self._election_candidates)) or 'none') + '.',
                    data={'candidates': self._election_candidates})
        candidates = list(self._election_candidates)
        voters = [s for s in self._election_voters if self.players[s]['alive']]
        if candidates and (yield from self._explosion(election=True)):
            return True
        if len(candidates) == 1:
            self.sheriff = candidates[0]
        elif candidates and voters:
            for round_index in range(2):
                votes = yield from self._ask(voters, 'sheriff_vote', [{'type': 'vote', 'target': t} for t in [None] + candidates])
                leaders = self._tally(votes, sheriff_weight=False, kind='sheriff_ballots')
                if len(leaders) == 1:
                    self.sheriff = leaders[0]
                    break
                if not leaders or round_index:
                    break
                candidates = sorted(leaders, reverse=True)
                self._election_candidates = list(candidates)
                for s in candidates:
                    if (yield from self._explosion(election=True)):
                        return True
                    yield from self._speech(s, 'tie_speech')
                if (yield from self._explosion(election=True)):
                    return True
        self._election_done = True
        self._event('sheriff', f'Seat {self.sheriff} is elected Sheriff.' if self.sheriff else 'No Sheriff is elected.', data={'sheriff': self.sheriff})
        return False

    def _tally(self, votes, sheriff_weight, kind):
        tally = Counter()
        for s, a in votes.items():
            if a['target'] is not None:
                tally[a['target']] += 1.5 if sheriff_weight and s == self.sheriff else 1
        self._event(kind, 'Ballots: ' + ', '.join(f'{s} → {a["target"] if a["target"] is not None else "abstain"}' for s, a in votes.items()) + '.',
                    data={'votes': {str(s): a['target'] for s, a in votes.items()}, 'tally': {str(s): n for s, n in tally.items()}})
        return sorted(s for s, n in tally.items() if n == max(tally.values())) if tally else []

    def _discussion(self):
        self.phase = 'discussion'
        alive = self._alive()
        if self.sheriff:
            a = (yield from self._ask([self.sheriff], 'direction', [{'type': 'direction', 'value': 'clockwise'}, {'type': 'direction', 'value': 'counterclockwise'}]))[self.sheriff]
            direction = 1 if a['value'] == 'clockwise' else -1
            anchor = self._night_deaths[0] if len(self._night_deaths) == 1 else self.sheriff
            order = [(anchor-1 + direction * i) % 12 + 1 for i in range(1, 13)]
            order = [s for s in order if s in alive and s != self.sheriff] + [self.sheriff]
        else:
            start = self._order_rng.choice(alive)
            direction = self._order_rng.choice([1, -1])
            order = [(start-1 + direction * i) % 12 + 1 for i in range(12)]
            order = [s for s in order if s in alive]
        self._event('speaking_order', 'Speaking order: ' + ', '.join(map(str, order)) + '.', data={'order': order})
        for s in order:
            if (yield from self._explosion()):
                return
            yield from self._speech(s, 'speech')
        self.phase = 'voting'
        eligible = [s for s in self._alive() if self.players[s]['revealed_role'] != 'idiot']
        candidates = list(eligible)
        for round_index in range(2):
            voters = [s for s in eligible if not round_index or s not in candidates]
            votes = yield from self._ask(voters, 'exile_vote', [{'type': 'vote', 'target': t} for t in [None] + candidates])
            leaders = self._tally(votes, sheriff_weight=True, kind='exile_ballots')
            if len(leaders) == 1:
                yield from self._exile(leaders[0])
                return
            if not leaders or round_index:
                self._event('no_exile', 'No player is exiled today.')
                return
            candidates = [s for s in order if s in leaders]
            for s in candidates:
                yield from self._speech(s, 'tie_speech')

    def _exile(self, seat):
        if self.players[seat]['role'] == 'idiot' and not self.idiot_revealed:
            self.idiot_revealed = True
            self.players[seat]['revealed_role'] = 'idiot'
            self._event('idiot_reveal', f'Seat {seat} reveals as Idiot and survives exile, losing voting rights.', seat=seat)
            if self.sheriff == seat:
                yield from self._badge(seat)
            yield from self._speech(seat, 'last_words')
            return
        self.players[seat]['alive'] = False
        self._event('exile', f'Seat {seat} is exiled.', seat=seat)
        if self._check_win():
            return
        if self.players[seat]['role'] == 'hunter':
            yield from self._hunter(seat, 'day')
            if self.winner:
                return
        yield from self._badge_if_needed()
        yield from self._speech(seat, 'last_words')

    def _hunter(self, seat, origin):
        action = (yield from self._ask([seat], 'hunter', [{'type': 'shoot', 'target': t} for t in [None] + self._alive()]))[seat]
        target = action['target']
        if target is None:
            self._event('hunter_declined', 'You decline to shoot.', seat=seat, audience=[seat])
            return
        self.players[seat]['revealed_role'] = 'hunter'
        self._event('hunter_shot', f'Hunter {seat} shoots seat {target}.', seat=seat, data={'target': target})
        self.players[target]['alive'] = False
        if self._check_win():
            return
        yield from self._badge_if_needed()
        if origin == 'day' or self.day == 1:
            yield from self._speech(target, 'last_words')

    def _badge_if_needed(self):
        if self.sheriff and not self.players[self.sheriff]['alive']:
            yield from self._badge(self.sheriff)

    def _badge(self, seat):
        targets = [s for s in self._alive() if s != seat and self.players[s]['revealed_role'] != 'idiot']
        a = (yield from self._ask([seat], 'badge', [{'type': 'badge', 'target': t} for t in [None] + targets]))[seat]
        self.sheriff = a['target']
        self._event('badge', f'The badge passes to seat {self.sheriff}.' if self.sheriff else 'The badge is destroyed.', seat=seat, data={'sheriff': self.sheriff})
