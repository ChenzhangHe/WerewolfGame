"""Batched inference, private notes, and immutable historical spectator views."""

from __future__ import annotations

import copy
from dataclasses import asdict, replace

from .engine import Game
from . import providers


class Runner:
    def __init__(self, configs, seed=1, language="en"):
        if language not in {"en", "zh"}:
            raise ValueError("Language must be en or zh.")
        configs = tuple(configs)
        if len(configs) != 12 or sorted(c.seat for c in configs) != list(range(1, 13)):
            raise ValueError("Configure exactly one player for each seat 1–12.")
        self.configs = tuple(replace(c, language=language) for c in sorted(configs, key=lambda c: c.seat))
        for config in self.configs:
            providers.check_credentials(config)
        self.language = language
        self.game = Game(seed=seed, names=[c.name for c in self.configs], language=language)
        self.status = "paused"
        self.error = None
        self._notes = {seat: "" for seat in range(1, 13)}
        self._records = []
        self._checkpoints = []
        self._batch_requests = None
        self._batch_responses = {}
        self._batch_record_indices = {}
        self._capture()

    def _capture(self):
        views = {"mystery": self.game.view("mystery"), "omniscient": self.game.view("omniscient")}
        views["omniscient"]["private_notes"] = copy.deepcopy(self._notes)
        for seat in range(1, 13):
            view = self.game.view("player", seat)
            view["private_notes"] = self._notes[seat]
            if "observation" in view:
                view["observation"]["private_notes"] = self._notes[seat]
            views[f"player:{seat}"] = view
        self._checkpoints.append(copy.deepcopy(views))

    @property
    def max_step(self):
        return len(self._checkpoints) - 1

    def snapshot(self, mode="mystery", seat=None):
        return self.replay(self.max_step, mode, seat)

    def replay(self, index, mode="mystery", seat=None):
        if type(index) is not int or not 0 <= index <= self.max_step:
            raise ValueError("Replay checkpoint is out of range.")
        if mode not in {"mystery", "omniscient", "player"}:
            raise ValueError("Unknown viewing mode.")
        if mode == "player" and (type(seat) is not int or not 1 <= seat <= 12):
            raise ValueError("Follow mode needs a seat from 1 to 12.")
        key = f"player:{seat}" if mode == "player" else mode
        result = copy.deepcopy(self._checkpoints[index][key])
        result.update({
            "language": self.language, "step": index, "max_step": self.max_step,
            "configs": [asdict(c) for c in self.configs],
            "status": self.status if index == self.max_step else "paused",
            "error": self.error if index == self.max_step else None,
        })
        return result

    def _pause_error(self, message):
        self.status = "error"
        self.error = message
        return self.snapshot()

    def step(self):
        pending = self.game.pending()
        if not pending:
            self.status = "finished" if self.game.view("mystery").get("winner") else "paused"
            return self.snapshot()
        if self._batch_requests is None:
            requests = {}
            try:
                # Build every request from the SAME uncommitted engine state.
                for decision in pending:
                    seat = decision["seat"]
                    requests[decision["id"]] = providers.build_request(
                        self.configs[seat - 1], self.game.observe(seat), decision, self._notes[seat]
                    )
            except providers.ProviderError as exc:
                return self._pause_error(str(exc))
            self._batch_requests = requests
        for decision in pending:
            decision_id = decision["id"]
            if decision_id in self._batch_responses:
                continue
            seat = decision["seat"]
            config = self.configs[seat - 1]
            assembled = self._batch_requests[decision_id]
            record = {"seat": seat, "request": copy.deepcopy(assembled),
                      "wire_request": providers.wire_request(config, assembled) if config.provider != "demo" else None,
                      "accepted": False}
            try:
                answer = providers.decide(config, assembled)
                providers.validate_action(answer, decision)
                record.update({"response": copy.deepcopy(dict(answer)),
                               "reported_model": getattr(answer, "reported_model", None),
                               "usage": getattr(answer, "usage", {}),
                               "raw_text": getattr(answer, "raw_text", None)})
                self._batch_responses[decision_id] = copy.deepcopy(dict(answer))
            except providers.ProviderError as exc:
                record["error"] = str(exc)
                self._records.append(record)
                return self._pause_error(str(exc))
            except Exception:
                # Raw exception messages can contain headers, tokens, or response bodies.
                record["error"] = "Player inference failed; inspect local provider configuration."
                self._records.append(record)
                return self._pause_error(record["error"])
            self._records.append(record)
            self._batch_record_indices[decision_id] = len(self._records) - 1
        responses = copy.deepcopy(self._batch_responses)
        try:
            # Notes live only in the runner. Engine accepts only action/speech fields.
            self.game.submit({key: {k: v for k, v in value.items() if k != "notes"}
                              for key, value in responses.items()})
        except ValueError:
            # Invalid choices are re-requested on explicit retry, never silently replaced.
            self._batch_requests = None
            self._batch_responses = {}
            self._batch_record_indices = {}
            return self._pause_error("Referee rejected the proposed batch; game paused without applying actions.")
        for decision in pending:
            response = responses[decision["id"]]
            if "notes" in response:
                self._notes[decision["seat"]] = response["notes"]
        # Mark only the responses actually used, including successes cached before a failure.
        for index in self._batch_record_indices.values():
            self._records[index]["accepted"] = True
        self._batch_requests = None
        self._batch_responses = {}
        self._batch_record_indices = {}
        self.error = None
        self.status = "finished" if self.game.view("mystery").get("winner") else "paused"
        self._capture()
        return self.snapshot()

    def export(self):
        return copy.deepcopy({
            "format": "werewolf-archive-v1", "ruleset": "rules-v1",
            "prompt_version": providers.PROMPT_VERSION, "language": self.language,
            "configs": [asdict(c) for c in self.configs],
            "inference": self._records, "game": self.game.export(),
            "checkpoints": self._checkpoints, "private_notes": self._notes,
        })
