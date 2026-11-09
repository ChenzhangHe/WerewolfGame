"""Batched inference, private notes, and immutable historical spectator views."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json

from .engine import Game
from . import providers


class Runner:
    def __init__(self, configs, seed=1, language="en", *, allow_format_repair=False):
        if language not in {"en", "zh"}:
            raise ValueError("Language must be en or zh.")
        if type(allow_format_repair) is not bool:
            raise ValueError("allow_format_repair must be a boolean.")
        self._allow_format_repair = allow_format_repair
        self._tool_prompt_version = providers.TOOLS_PROMPT_VERSION
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
        self._batch_repair_used = set()
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

    @property
    def allow_format_repair(self):
        """Frozen game policy, separate from the information sent to players."""
        return self._allow_format_repair

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
            "allow_format_repair": self.allow_format_repair,
            "status": self.status if index == self.max_step else "paused",
            "error": self.error if index == self.max_step else None,
        })
        return result

    def _pause_error(self, message):
        self.status = "error"
        self.error = message
        return self.snapshot()

    @staticmethod
    def _response_fields(answer):
        """Retain only the parsed action and explicitly safe provider metadata."""
        return {
            "response": copy.deepcopy(dict(answer)),
            "reported_model": getattr(answer, "reported_model", None),
            "usage": copy.deepcopy(getattr(answer, "usage", {})),
            "raw_text": getattr(answer, "raw_text", None),
            "tool_trace": copy.deepcopy(getattr(answer, "tool_trace", [])),
        }

    def _infer_decision(self, decision):
        """Run one seat in isolation; only the calling step mutates runner state."""
        decision_id = decision["id"]
        seat = decision["seat"]
        config = self.configs[seat - 1]
        original_request = copy.deepcopy(self._batch_requests[decision_id])
        assembled = original_request
        repair_used = decision_id in self._batch_repair_used
        repair = False
        records = []
        while True:
            record = {"seat": seat, "kind": decision["kind"], "batch_index": self.max_step,
                      "request": copy.deepcopy(assembled), "repair": repair,
                      "accepted": False}
            try:
                record["wire_request"] = providers.wire_request(config, assembled) if config.provider != "demo" else None
                answer = providers.decide(config, assembled)
                providers.validate_action(answer, decision)
                record.update(self._response_fields(answer))
            except providers.ProviderError as exc:
                record["error"] = str(exc)
                if hasattr(exc, "tool_trace"):
                    record["tool_trace"] = copy.deepcopy(exc.tool_trace)
                details = getattr(exc, "validation_details", None)
                if isinstance(details, dict):
                    record["validation_details"] = copy.deepcopy(details)
                rejected = getattr(exc, "rejected_result", None)
                rejected_text = getattr(exc, "rejected_text", None)
                if isinstance(rejected, dict):
                    record.update(self._response_fields(rejected))
                    record["rejected"] = True
                    record["repairable"] = True
                    repair_input = rejected
                elif isinstance(rejected_text, str):
                    # Only the model's final action content is attached by the
                    # adapter. Never archive an HTTP body or reasoning content.
                    record.update({"rejected_text": rejected_text, "raw_text": rejected_text,
                                   "reported_model": getattr(exc, "reported_model", None),
                                   "usage": copy.deepcopy(getattr(exc, "usage", {})),
                                   "rejected": True,
                                   "repairable": getattr(exc, "repairable", False) is True})
                    repair_input = rejected_text if record["repairable"] else None
                else:
                    repair_input = None
                # A rejected parsed action can have less metadata than the
                # enclosing tool failure. Keep the actual failed conversation.
                if hasattr(exc, "tool_trace"):
                    record["tool_trace"] = copy.deepcopy(exc.tool_trace)
                records.append(record)
                if (config.interaction_mode == "json" and self.allow_format_repair
                        and repair_input is not None and not repair_used):
                    repair_used = True
                    try:
                        assembled = providers.build_repair_request(original_request, repair_input)
                    except Exception:
                        return records, None, "Could not assemble a safe action-format repair; game paused.", repair_used
                    repair = True
                    continue
                return records, None, str(exc), repair_used
            except Exception:
                # Raw exceptions can contain headers, tokens, or response bodies.
                record["error"] = "Player inference failed; inspect local provider configuration."
                records.append(record)
                return records, None, record["error"], repair_used
            records.append(record)
            return records, copy.deepcopy(dict(answer)), None, repair_used

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
                        self.configs[seat - 1], self.game.observe(seat), decision, self._notes[seat],
                        tool_prompt_version=self._tool_prompt_version,
                    )
            except providers.ProviderError as exc:
                return self._pause_error(str(exc))
            self._batch_requests = requests
        unresolved = [d for d in pending if d["id"] not in self._batch_responses]
        failures = []
        if unresolved:
            # All requests already exist. Workers receive only their own copy;
            # they cannot submit actions or inspect another worker's response.
            with ThreadPoolExecutor(max_workers=min(4, len(unresolved)), thread_name_prefix="werewolf-player") as pool:
                futures = [pool.submit(self._infer_decision, decision) for decision in unresolved]
                # Process completed results in decision order, not network order.
                # Even if one seat fails, finish/cache every other paid response.
                for decision, future in zip(unresolved, futures):
                    records, answer, failure, repair_used = future.result()
                    self._records.extend(records)
                    decision_id = decision["id"]
                    if repair_used:
                        self._batch_repair_used.add(decision_id)
                    if answer is not None:
                        self._batch_responses[decision_id] = answer
                        self._batch_record_indices[decision_id] = len(self._records) - 1
                    if failure is not None:
                        failures.append(failure)
            if failures:
                return self._pause_error(failures[0])
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
            self._batch_repair_used = set()
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
        self._batch_repair_used = set()
        self.error = None
        self.status = "finished" if self.game.view("mystery").get("winner") else "paused"
        self._capture()
        return self.snapshot()

    def export(self):
        pending_batch = []
        if self._batch_requests is not None:
            for decision in self.game.pending():
                decision_id = decision["id"]
                pending_batch.append({
                    "seat": decision["seat"], "kind": decision["kind"],
                    "request": self._batch_requests[decision_id],
                    "response": self._batch_responses.get(decision_id),
                    "record_index": self._batch_record_indices.get(decision_id),
                    "repair_used": decision_id in self._batch_repair_used,
                })
        return copy.deepcopy({
            "format": "werewolf-archive-v1", "ruleset": "rules-v1",
            "prompt_version": providers.PROMPT_VERSION, "language": self.language,
            "tool_prompt_version": self._tool_prompt_version,
            "allow_format_repair": self.allow_format_repair,
            "configs": [asdict(c) for c in self.configs],
            "inference": self._records, "game": self.game.export(),
            "checkpoints": self._checkpoints, "private_notes": self._notes,
            "pending_batch": pending_batch,
        })

    @classmethod
    def from_archive(cls, archive):
        """Restore a trusted local archive by validating and replaying actions.

        No provider is called, no credential is read, and no accepted action is
        inferred again. Random routing UUIDs are remapped to fresh decision IDs.
        Historical views are verified against the reconstructed referee instead
        of trusting arbitrary spectator projections in the input.
        """
        try:
            return cls._restore_archive(archive)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError, providers.ProviderError):
            raise ValueError("Invalid or inconsistent game archive.") from None

    @staticmethod
    def _canonical(value):
        # JSON round trips normalize integer seat keys in archived dictionaries.
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))

    @classmethod
    def _restore_archive(cls, source):
        archive = cls._canonical(source)
        if not isinstance(archive, dict) or archive.get("format") != "werewolf-archive-v1" or archive.get("ruleset") != "rules-v1":
            raise ValueError("Unsupported archive.")
        language = archive["language"]
        if language not in ("en", "zh"):
            raise ValueError("Invalid language.")
        configs = tuple(providers.PlayerConfig(**c) for c in archive["configs"])
        if len(configs) != 12 or sorted(c.seat for c in configs) != list(range(1, 13)) or any(c.language != language for c in configs):
            raise ValueError("Invalid player configurations.")
        configs = tuple(sorted(configs, key=lambda c: c.seat))
        game_data = archive["game"]
        players = game_data["players"]
        if game_data.get("ruleset") != "rules-v1" or game_data.get("language") != language or len(players) != 12:
            raise ValueError("Invalid referee archive.")
        if sorted(p["seat"] for p in players) != list(range(1, 13)):
            raise ValueError("Invalid seats.")
        players = sorted(players, key=lambda p: p["seat"])
        if any(p["name"] != c.name for p, c in zip(players, configs)):
            raise ValueError("Names disagree.")
        result = cls.__new__(cls)
        result.configs = configs
        result.language = language
        result._tool_prompt_version = archive.get("tool_prompt_version", "player-tools-v1")
        if result._tool_prompt_version not in {"player-tools-v1", "player-tools-v2", "player-tools-v3", "player-tools-v4", "player-tools-v5", "player-tools-v6", "player-tools-v7", "player-tools-v8", "player-tools-v9"}:
            raise ValueError("Unsupported player tool protocol.")
        # Earlier archives predate this explicit policy and always repaired.
        policy = archive.get("allow_format_repair", True)
        if type(policy) is not bool:
            raise ValueError("Invalid format-repair policy.")
        result._allow_format_repair = policy
        result.game = Game(seed=game_data["seed"], names=[c.name for c in configs],
                           roles=[p["role"] for p in players], language=language)
        result.status = "paused"
        result.error = None
        result._records = []
        result._checkpoints = []
        result._batch_requests = None
        result._batch_responses = {}
        result._batch_record_indices = {}
        result._batch_repair_used = set()
        saved_checkpoints = archive["checkpoints"]
        batches = game_data["submitted_batches"]
        if not isinstance(saved_checkpoints, list) or not isinstance(batches, list) or len(saved_checkpoints) != len(batches) + 1:
            raise ValueError("Invalid checkpoint count.")

        def read_notes(raw):
            if not isinstance(raw, dict) or set(raw) != {str(s) for s in range(1, 13)}:
                raise ValueError("Invalid note owners.")
            if any(not isinstance(v, str) or len(v) > providers.MAX_NOTES_CHARS for v in raw.values()):
                raise ValueError("Invalid private notes.")
            return {int(s): text for s, text in raw.items()}

        def checkpoint(index):
            saved = saved_checkpoints[index]
            result._notes = read_notes(saved["omniscient"]["private_notes"])
            result._capture()
            if cls._canonical(result._checkpoints[-1]) != saved:
                raise ValueError("Historical view disagrees with referee replay.")

        checkpoint(0)
        for index, batch in enumerate(batches):
            current = result.game.pending()
            archived = batch["decisions"]
            actions = batch["actions"]
            if not isinstance(archived, list) or len(current) != len(archived) or not isinstance(actions, dict):
                raise ValueError("Invalid batch.")
            if set(actions) != {d["id"] for d in archived}:
                raise ValueError("Invalid submitted actions.")
            archived_by_seat = {d["seat"]: d for d in archived}
            if len(archived_by_seat) != len(archived) or set(archived_by_seat) != {d["seat"] for d in current}:
                raise ValueError("Decision seats disagree.")
            remapped = {}
            for decision in current:
                original = archived_by_seat[decision["seat"]]
                if original["kind"] != decision["kind"] or original["options"] != decision["options"]:
                    raise ValueError("Decision schema disagrees.")
                remapped[decision["id"]] = actions[original["id"]]
            result.game.submit(remapped)
            checkpoint(index + 1)
        actual = result.game.export()
        for field in ("ruleset", "language", "seed", "players", "winner", "events"):
            if cls._canonical(actual[field]) != game_data[field]:
                raise ValueError("Final referee state disagrees.")
        if read_notes(archive["private_notes"]) != result._notes:
            raise ValueError("Final private notes disagree.")
        records = archive["inference"]
        if not isinstance(records, list):
            raise ValueError("Invalid inference history.")
        for record in records:
            if (not isinstance(record, dict) or type(record.get("seat")) is not int
                    or not 1 <= record["seat"] <= 12 or type(record.get("accepted")) is not bool
                    or not isinstance(record.get("request"), dict)):
                raise ValueError("Invalid inference record.")
            if "response" in record and not isinstance(record["response"], dict):
                raise ValueError("Invalid parsed response.")
            if not result.allow_format_repair and record.get("repair"):
                raise ValueError("Recorded format repair contradicts the archived game policy.")
        result._records = copy.deepcopy(records)
        result._restore_pending(archive.get("pending_batch"))
        result.status = "finished" if result.game.view("mystery").get("winner") else "paused"
        return result

    def _restore_pending(self, saved):
        """Recover legal uncommitted successes without exposing other seats."""
        pending = self.game.pending()
        if not pending:
            if saved:
                raise ValueError("Finished game has pending responses.")
            return
        if saved is not None and not isinstance(saved, list):
            raise ValueError("Invalid pending batch.")
        if saved:
            by_seat = {entry["seat"]: entry for entry in saved}
            if len(by_seat) != len(saved) or set(by_seat) != {d["seat"] for d in pending}:
                raise ValueError("Pending seats disagree.")
        else:
            by_seat = {}
        requests = {}
        for decision in pending:
            seat = decision["seat"]
            config = self.configs[seat - 1]
            fresh = providers.build_request(config, self.game.observe(seat), decision, self._notes[seat],
                                            tool_prompt_version=self._tool_prompt_version)
            requests[decision["id"]] = fresh
            entry = by_seat.get(seat)
            if entry is not None:
                if (entry["kind"] != decision["kind"]
                        or self._canonical(entry["request"]["input"]) != self._canonical(fresh["input"])
                        or self._canonical(entry["request"].get("tool_context")) != self._canonical(fresh.get("tool_context"))):
                    raise ValueError("Pending request disagrees with player context.")
                if entry.get("repair_used"):
                    if not self.allow_format_repair:
                        raise ValueError("Pending format repair contradicts the archived game policy.")
                    self._batch_repair_used.add(decision["id"])
                if type(entry.get("repair_used")) is not bool:
                    raise ValueError("Invalid pending repair flag.")
                response = entry.get("response")
                record_index = entry.get("record_index")
                if response is None:
                    if record_index is not None:
                        raise ValueError("Pending record has no response.")
                    continue
                if type(record_index) is not int or not 0 <= record_index < len(self._records):
                    raise ValueError("Invalid pending response record.")
                record = self._records[record_index]
                if self._canonical(record.get("response")) != self._canonical(response):
                    raise ValueError("Pending response record disagrees.")
                self._validate_cached_record(record_index, decision, fresh)
                if record.get("repair") and not entry["repair_used"]:
                    raise ValueError("Repaired response lacks its repair flag.")
                providers.validate_action(response, decision)
                self._batch_responses[decision["id"]] = copy.deepcopy(response)
                self._batch_record_indices[decision["id"]] = record_index
            else:
                # Older archives have no pending-cache field. A current-context
                # record can still save a valid already-paid response. Never use
                # a response from an accepted or rejected earlier decision.
                for index in range(len(self._records) - 1, -1, -1):
                    record = self._records[index]
                    if (record["seat"] != seat or record.get("accepted") or record.get("rejected")
                            or "response" not in record or record.get("error")):
                        continue
                    try:
                        self._validate_cached_record(index, decision, fresh)
                        providers.validate_action(record["response"], decision)
                    except (ValueError, providers.ProviderError):
                        continue
                    self._batch_responses[decision["id"]] = copy.deepcopy(record["response"])
                    self._batch_record_indices[decision["id"]] = index
                    if record.get("repair"):
                        self._batch_repair_used.add(decision["id"])
                    break
        self._batch_requests = requests

    def _record_matches_task(self, record, decision, fresh):
        """A cached response needs provenance, not merely a legal action shape."""
        stored = record.get("request")
        return (
            record.get("seat") == decision["seat"]
            and record.get("kind") == decision["kind"]
            and type(record.get("batch_index")) is int
            and record["batch_index"] == self.max_step
            and record.get("accepted") is False
            and isinstance(stored, dict)
            and all(stored.get(key) == fresh.get(key) for key in ("provider", "model", "language"))
            and stored.get("tool_context") == fresh.get("tool_context")
        )

    def _validate_cached_record(self, index, decision, fresh):
        record = self._records[index]
        if (not self._record_matches_task(record, decision, fresh)
                or record.get("rejected") or "error" in record
                or type(record.get("repair")) is not bool):
            raise ValueError("Cached response is not a successful response for the current task.")
        stored_input = record["request"].get("input")
        expected_input = copy.deepcopy(fresh["input"])
        if not record["repair"]:
            if self._canonical(stored_input) != self._canonical(expected_input):
                raise ValueError("Cached response has a different player context.")
            return
        if not isinstance(stored_input, dict):
            raise ValueError("Invalid repaired response input.")
        fields = [key for key in ("rejected_action", "rejected_output") if key in stored_input]
        if len(fields) != 1:
            raise ValueError("Repair must identify exactly one rejected output.")
        field = fields[0]
        rejected = stored_input[field]
        if field == "rejected_action" and not isinstance(rejected, dict):
            raise ValueError("Invalid rejected action.")
        if field == "rejected_output" and not isinstance(rejected, str):
            raise ValueError("Invalid rejected text.")
        expected_input[field] = rejected
        if self._canonical(stored_input) != self._canonical(expected_input):
            raise ValueError("Repair changed the player's original context.")
        for earlier in self._records[:index]:
            if (not self._record_matches_task(earlier, decision, fresh)
                    or earlier.get("rejected") is not True or not earlier.get("error")
                    or earlier.get("repair") is not False
                    or self._canonical(earlier["request"].get("input")) != self._canonical(fresh["input"])):
                continue
            prior_output = earlier.get("response") if field == "rejected_action" else earlier.get("rejected_text")
            if self._canonical(prior_output) == self._canonical(rejected):
                if field == "rejected_output" and earlier.get("repairable") is not True:
                    continue
                return
        raise ValueError("Repair feedback has no matching private rejection for this task.")
