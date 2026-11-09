import copy
import json
import threading
import unittest
from unittest.mock import patch

from werewolf.providers import DecisionResult, PlayerConfig, ProviderError, build_request
from werewolf.runner import Runner


def configs():
    return [PlayerConfig(seat, f"Player {seat}") for seat in range(1, 13)]


class RunnerTests(unittest.TestCase):
    def test_batch_failure_preserves_successes_without_partial_commit(self):
        runner = Runner(configs())
        pending = runner.game.pending()
        self.assertGreater(len(pending), 1)
        before = runner.game.export()
        first = pending[0]["seat"]
        failing = pending[1]["seat"]
        calls = []
        real_decide = __import__("werewolf.providers", fromlist=["decide"]).decide
        def decide(config, request):
            calls.append(config.seat)
            if config.seat == failing:
                raise ProviderError("Test provider unavailable.")
            return real_decide(config, request)
        with patch("werewolf.runner.providers.decide", side_effect=decide):
            snapshot = runner.step()
        self.assertEqual("error", snapshot["status"])
        self.assertEqual(before, runner.game.export())
        self.assertEqual(0, runner.max_step)
        with patch("werewolf.runner.providers.decide", wraps=real_decide) as retry:
            runner.step()
            self.assertNotIn(first, [call.args[0].seat for call in retry.call_args_list])
        self.assertEqual(1, runner.max_step)
        records = runner.export()["inference"]
        self.assertEqual(len(pending), sum(r["accepted"] for r in records))
        self.assertEqual(1, sum("error" in r for r in records))

    def test_private_notes_stay_with_their_seat(self):
        runner = Runner(configs())
        pending = runner.game.pending()
        seat = pending[0]["seat"]
        runner._notes[seat] = "PRIVATE_SENTINEL"
        other = next(s for s in range(1, 13) if s != seat)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(runner.snapshot("player", other)))
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(runner.snapshot("mystery")))
        for decision in pending:
            request = build_request(runner.configs[decision["seat"] - 1], runner.game.observe(decision["seat"]),
                                    decision, runner._notes[decision["seat"]])
            self.assertEqual(decision["seat"] == seat, "PRIVATE_SENTINEL" in json.dumps(request))

    def test_replay_is_detached_and_spectating_does_not_affect_requests(self):
        runner = Runner(configs())
        old = runner.replay(0)
        pending = runner.game.pending()
        before = [build_request(runner.configs[d["seat"] - 1], runner.game.observe(d["seat"]), d) for d in pending]
        runner.snapshot("omniscient")
        for seat in range(1, 13):
            runner.snapshot("player", seat)
        after = [build_request(runner.configs[d["seat"] - 1], runner.game.observe(d["seat"]), d) for d in pending]
        self.assertEqual(before, after)
        runner.step()
        replay = runner.replay(0)
        for key in ("day", "phase", "players", "events"):
            self.assertEqual(old[key], replay[key])
        replay["players"][0]["name"] = "mutated"
        self.assertNotEqual("mutated", runner.replay(0)["players"][0]["name"])

    def test_game_language_frozen_into_every_config_and_prompt(self):
        runner = Runner(configs(), language="zh")
        self.assertTrue(all(c.language == "zh" for c in runner.configs))
        self.assertEqual("zh", runner.snapshot()["language"])
        for d in runner.game.pending():
            request = build_request(runner.configs[d["seat"] - 1], runner.game.observe(d["seat"]), d)
            self.assertEqual("zh", request["language"])

    def test_no_postgame_roles_leak_backward(self):
        runner = Runner(configs())
        initial = runner.replay(0)
        for _ in range(1000):
            if runner.step()["status"] in {"finished", "error"}:
                break
        self.assertEqual("finished", runner.status, runner.error)
        self.assertIn(runner.snapshot()["winner"], {"good", "wolves"})
        self.assertTrue(all("role" in p for p in runner.snapshot()["players"]))
        self.assertTrue(all("role" not in p for p in runner.replay(0)["players"]))
        self.assertEqual(initial["events"], runner.replay(0)["events"])

    def test_raw_exceptions_do_not_leak_credentials(self):
        runner = Runner(configs())
        with patch("werewolf.runner.providers.decide", side_effect=RuntimeError("Bearer SECRET")):
            result = runner.step()
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("SECRET", json.dumps(runner.export()))

    def test_rejected_action_is_recorded_and_repaired_once_privately(self):
        runner = Runner(configs(), allow_format_repair=True)
        first = runner.game.pending()[0]
        first_seat = first["seat"]
        real_decide = __import__("werewolf.providers", fromlist=["decide"]).decide
        requests = []
        first_attempt = True
        def decide(config, request):
            nonlocal first_attempt
            requests.append((config.seat, copy.deepcopy(request)))
            if config.seat == first_seat and first_attempt:
                first_attempt = False
                rejected = DecisionResult({"type": "invalid", "notes": "PRIVATE_BAD_ACTION"},
                                          model="reported-test-model", usage={"total_tokens": 12},
                                          raw_text='{"type":"invalid","notes":"PRIVATE_BAD_ACTION"}')
                failure = ProviderError("Player proposed an action outside its supplied legal options.")
                failure.rejected_result = rejected
                raise failure
            return real_decide(config, request)
        with patch("werewolf.runner.providers.decide", side_effect=decide):
            result = runner.step()
        self.assertNotEqual("error", result["status"])
        self.assertEqual(2, sum(seat == first_seat for seat, _ in requests))
        records = runner.export()["inference"]
        failed = records[0]
        self.assertTrue(failed["rejected"])
        self.assertFalse(failed["accepted"])
        self.assertEqual("reported-test-model", failed["reported_model"])
        self.assertEqual({"total_tokens": 12}, failed["usage"])
        self.assertIn("PRIVATE_BAD_ACTION", failed["raw_text"])
        self.assertTrue(records[1]["repair"])
        self.assertTrue(records[1]["accepted"])
        for seat, request in requests:
            if seat != first_seat:
                self.assertNotIn("PRIVATE_BAD_ACTION", json.dumps(request))
        self.assertNotIn("PRIVATE_BAD_ACTION", json.dumps(runner.snapshot("mystery")))
        self.assertNotIn("PRIVATE_BAD_ACTION", json.dumps(runner.snapshot("player", 1 if first_seat != 1 else 2)))

    def test_repair_failure_is_bounded_and_does_not_commit_or_replace_notes(self):
        runner = Runner(configs(), allow_format_repair=True)
        before = runner.game.export()
        def reject(config, request):
            failure = ProviderError("Invalid action.")
            failure.rejected_result = DecisionResult({"type": "invalid", "notes": "DO_NOT_KEEP"})
            raise failure
        with patch("werewolf.runner.providers.decide", side_effect=reject) as call:
            result = runner.step()
            self.assertEqual(2 * len(runner.game.pending()), call.call_count)
            self.assertEqual("error", result["status"])
            runner.step()  # Explicit retry does not add another automatic repair.
            self.assertEqual(3 * len(runner.game.pending()), call.call_count)
        self.assertEqual(before, runner.game.export())
        self.assertTrue(all(not note for note in runner._notes.values()))

    def test_restore_replays_without_inference_and_preserves_context(self):
        runner = Runner(configs(), seed=9, language="zh")
        for _ in range(12):
            runner.step()
        # JSON serialization changes integer dictionary keys to strings.
        archived = json.loads(json.dumps(runner.export()))
        with patch("werewolf.runner.providers.decide", side_effect=AssertionError("No inference on restore")), \
             patch("werewolf.runner.providers.check_credentials", side_effect=AssertionError("No credential check on restore")):
            restored = Runner.from_archive(archived)
        self.assertEqual(runner.configs, restored.configs)
        self.assertEqual(runner.max_step, restored.max_step)
        for seat in range(1, 13):
            self.assertEqual(runner.game.observe(seat), restored.game.observe(seat))
        self.assertEqual(Runner._canonical(runner.export()["checkpoints"]),
                         Runner._canonical(restored.export()["checkpoints"]))
        self.assertEqual([(d["seat"], d["kind"], d["options"]) for d in runner.game.pending()],
                         [(d["seat"], d["kind"], d["options"]) for d in restored.game.pending()])
        restored.step()
        self.assertEqual(runner.max_step + 1, restored.max_step)

    def test_restore_preserves_successful_uncommitted_responses(self):
        runner = Runner(configs())
        pending = runner.game.pending()
        first, failing = pending[0]["seat"], pending[1]["seat"]
        real_decide = __import__("werewolf.providers", fromlist=["decide"]).decide
        def decide(config, request):
            if config.seat == failing:
                raise ProviderError("Transient test failure.")
            return real_decide(config, request)
        with patch("werewolf.runner.providers.decide", side_effect=decide):
            runner.step()
        archived = json.loads(json.dumps(runner.export()))
        restored = Runner.from_archive(archived)
        self.assertEqual(len(pending) - 1, len(restored._batch_responses))
        with patch("werewolf.runner.providers.decide", wraps=real_decide) as resumed:
            restored.step()
        self.assertNotIn(first, [call.args[0].seat for call in resumed.call_args_list])
        self.assertEqual(1, restored.max_step)
        self.assertEqual(len(pending), sum(r["accepted"] for r in restored.export()["inference"]))

    def _archive_with_pending_successes(self, *, repair=False, raw_repair=False):
        runner = Runner(configs(), allow_format_repair=repair)
        pending = runner.game.pending()
        successful, failing = pending[0]["seat"], pending[1]["seat"]
        real_decide = __import__("werewolf.providers", fromlist=["decide"]).decide
        rejected_once = False
        lock = threading.Lock()
        def decide(config, request):
            nonlocal rejected_once
            if config.seat == failing:
                raise ProviderError("Synthetic connection failure.")
            with lock:
                if config.seat == successful and repair and not rejected_once:
                    rejected_once = True
                    failure = ProviderError("Synthetic format failure.")
                    if raw_repair:
                        failure.rejected_text = "not JSON"
                        failure.reported_model = "test-model"
                        failure.usage = {"total_tokens": 4}
                        failure.repairable = True
                    else:
                        failure.rejected_result = DecisionResult({"type": "invalid"})
                    raise failure
            return real_decide(config, request)
        with patch("werewolf.runner.providers.decide", side_effect=decide):
            runner.step()
        self.assertEqual("error", runner.status)
        archive = runner.export()
        entry = next(e for e in archive["pending_batch"] if e["seat"] == successful)
        self.assertIsNotNone(entry["response"])
        return archive, entry["record_index"]

    def test_restore_rejects_stale_cached_task_batch_context_and_rejected_flags(self):
        archive, index = self._archive_with_pending_successes()
        mutations = [
            lambda r: r.update(kind="exile_vote"),
            lambda r: r.update(batch_index=99),
            lambda r: r.update(batch_index=True),
            lambda r: r.update(rejected=True),
            lambda r: r.update(error="Synthetic stale error"),
            lambda r: r["request"]["input"]["observation"].update(day=99),
            lambda r: r["request"]["input"].update(private_notes="Different private context"),
            lambda r: r["request"].update(model="different-model"),
            lambda r: r["request"]["input"].update(rejected_action={"type": "invalid"}),
        ]
        for number, mutate in enumerate(mutations):
            changed = copy.deepcopy(archive)
            mutate(changed["inference"][index])
            with self.subTest(mutation=number), self.assertRaises(ValueError):
                Runner.from_archive(changed)

    def test_restore_validates_repair_provenance_and_preserves_valid_repair(self):
        archive, index = self._archive_with_pending_successes(repair=True)
        restored = Runner.from_archive(archive)
        self.assertGreater(len(restored._batch_responses), 0)
        self.assertTrue(restored._batch_repair_used)
        rejected_index = index - 1
        mutations = [
            lambda a: a.update(allow_format_repair=False),
            lambda a: a["inference"][rejected_index].update(seat=12),
            lambda a: a["inference"][rejected_index].update(kind="wolf_attack"),
            lambda a: a["inference"][rejected_index].update(batch_index=99),
            lambda a: a["inference"][rejected_index].update(accepted=True),
            lambda a: a["inference"][rejected_index].update(rejected=False),
            lambda a: a["inference"][rejected_index]["request"]["input"].update(private_notes="Other context"),
            lambda a: a["inference"][index]["request"]["input"].update(rejected_action={"type": "other"}),
            lambda a: a["inference"][index]["request"]["input"].update(rejected_output="extra raw feedback"),
            lambda a: a["inference"][index]["request"]["input"]["observation"].update(day=99),
            lambda a: next(e for e in a["pending_batch"] if e["record_index"] == index).update(repair_used=False),
        ]
        for number, mutate in enumerate(mutations):
            changed = copy.deepcopy(archive)
            mutate(changed)
            with self.subTest(mutation=number), self.assertRaises(ValueError):
                Runner.from_archive(changed)

    def test_rejected_text_is_recorded_and_repaired_but_truncation_is_not(self):
        archive, index = self._archive_with_pending_successes(repair=True, raw_repair=True)
        rejected = archive["inference"][index - 1]
        self.assertEqual("not JSON", rejected["rejected_text"])
        self.assertEqual("not JSON", rejected["raw_text"])
        self.assertEqual("test-model", rejected["reported_model"])
        self.assertEqual({"total_tokens": 4}, rejected["usage"])
        self.assertEqual("not JSON", archive["inference"][index]["request"]["input"]["rejected_output"])
        Runner.from_archive(archive)
        changed = copy.deepcopy(archive)
        changed["inference"][index - 1]["rejected_text"] = "Someone else's rejected output"
        with self.assertRaises(ValueError):
            Runner.from_archive(changed)
        runner = Runner(configs(), allow_format_repair=True)
        before = runner.game.export()
        pending_count = len(runner.game.pending())
        def truncated(config, request):
            failure = ProviderError("Synthetic token limit.")
            failure.rejected_text = '{"type":'
            failure.reported_model = "truncated-model"
            failure.usage = {"total_tokens": 4096}
            failure.repairable = False
            raise failure
        with patch("werewolf.runner.providers.decide", side_effect=truncated) as called:
            runner.step()
        self.assertEqual(pending_count, called.call_count)
        self.assertEqual(before, runner.game.export())
        self.assertTrue(all(r["raw_text"] == '{"type":' and not r["repairable"]
                            for r in runner.export()["inference"]))
        self.assertFalse(runner._batch_repair_used)

    def test_parallel_batch_has_four_worker_limit_and_no_early_submit(self):
        runner = Runner(configs())
        # Reach the simultaneous public nomination batch with twelve decisions.
        while runner.game.pending()[0]["kind"] != "nominate":
            runner.step()
        pending = runner.game.pending()
        self.assertEqual(12, len(pending))
        before = runner.game.export()
        gate = threading.Event()
        four_started = threading.Event()
        guard = threading.Lock()
        active = 0
        peak = 0
        called = []
        real_decide = __import__("werewolf.providers", fromlist=["decide"]).decide
        def decide(config, request):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
                called.append(config.seat)
                if active == 4:
                    four_started.set()
            try:
                if not gate.wait(5):
                    raise AssertionError("Test inference gate timed out")
                return real_decide(config, request)
            finally:
                with guard:
                    active -= 1
        step_results = []
        with patch("werewolf.runner.providers.decide", side_effect=decide), \
             patch.object(runner.game, "submit", wraps=runner.game.submit) as submit:
            worker = threading.Thread(target=lambda: step_results.append(runner.step()))
            worker.start()
            try:
                self.assertTrue(four_started.wait(5), "Four calls should start concurrently")
                self.assertEqual(4, len(called))
                self.assertEqual(before, runner.game.export())
                submit.assert_not_called()
                # Every request was frozen before the first group started.
                self.assertEqual(12, len(runner._batch_requests))
            finally:
                gate.set()
                worker.join(10)
            self.assertFalse(worker.is_alive())
            submit.assert_called_once()
        self.assertEqual(4, peak)
        self.assertEqual(12, len(called))
        self.assertNotEqual("error", step_results[0]["status"])

    def test_parallel_failure_retains_later_successes_and_deterministic_archive_order(self):
        runner = Runner(configs())
        pending = runner.game.pending()
        before = runner.game.export()
        first_seat = pending[0]["seat"]
        started = threading.Barrier(len(pending))
        real_decide = __import__("werewolf.providers", fromlist=["decide"]).decide
        completed = []
        guard = threading.Lock()
        def decide(config, request):
            started.wait(timeout=5)
            if config.seat == first_seat:
                raise ProviderError("Synthetic first-seat failure.")
            answer = real_decide(config, request)
            with guard:
                completed.append(config.seat)
            return answer
        with patch("werewolf.runner.providers.decide", side_effect=decide):
            result = runner.step()
        self.assertEqual("error", result["status"])
        self.assertEqual(before, runner.game.export())
        self.assertEqual(len(pending) - 1, len(runner._batch_responses))
        self.assertEqual(len(pending) - 1, len(completed))
        records = runner.export()["inference"]
        self.assertEqual([d["seat"] for d in pending], [r["seat"] for r in records])
        self.assertTrue(all(not r["accepted"] for r in records))
        with patch("werewolf.runner.providers.decide", wraps=real_decide) as retry:
            runner.step()
        self.assertEqual([first_seat], [c.args[0].seat for c in retry.call_args_list])
        self.assertEqual(1, runner.max_step)

    def test_restore_legacy_archive_without_pending_cache(self):
        runner = Runner(configs())
        runner.step()
        archived = runner.export()
        del archived["pending_batch"]
        del archived["allow_format_repair"]
        restored = Runner.from_archive(archived)
        self.assertTrue(restored.allow_format_repair)
        self.assertEqual(runner.game.observe(1), restored.game.observe(1))
        restored.step()
        self.assertEqual(2, restored.max_step)

    def test_new_games_pause_on_invalid_output_by_default_and_archive_diagnostics(self):
        runner = Runner(configs())
        self.assertFalse(runner.allow_format_repair)
        before = runner.game.export()
        count = len(runner.game.pending())
        def reject(config, request):
            failure = ProviderError("Invalid action shape.")
            failure.rejected_result = DecisionResult({"type": "invalid"}, raw_text='{"type":"invalid"}')
            failure.validation_details = {"category": "illegal_action", "expected_types": ["discuss"],
                                          "returned_type": "invalid", "missing_fields": [],
                                          "extra_fields": [], "invalid_fields": ["type"]}
            raise failure
        with patch("werewolf.runner.providers.decide", side_effect=reject) as called, \
             patch("werewolf.runner.providers.build_repair_request") as repair:
            result = runner.step()
            self.assertEqual(count, called.call_count)
            repair.assert_not_called()
        self.assertEqual("error", result["status"])
        self.assertEqual(before, runner.game.export())
        records = runner.export()["inference"]
        self.assertTrue(all(r["validation_details"]["category"] == "illegal_action" for r in records))
        self.assertNotIn("validation_details", json.dumps(runner.snapshot("mystery")))
        self.assertNotIn("validation_details", json.dumps(runner.snapshot("player", 1)))
        self.assertFalse(runner._batch_repair_used)

    def test_format_repair_policy_is_strict_frozen_preserved_and_not_a_model_input(self):
        for value in (0, 1, None, "true", [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Runner(configs(), allow_format_repair=value)
        for enabled in (False, True):
            runner = Runner(configs(), allow_format_repair=enabled)
            with self.assertRaises(AttributeError):
                runner.allow_format_repair = not enabled
            for decision in runner.game.pending():
                request = build_request(runner.configs[decision["seat"] - 1], runner.game.observe(decision["seat"]), decision)
                self.assertNotIn("allow_format_repair", json.dumps(request))
            runner.step()
            archive = runner.export()
            self.assertIs(enabled, archive["allow_format_repair"])
            restored = Runner.from_archive(archive)
            self.assertIs(enabled, restored.allow_format_repair)
            self.assertIs(enabled, restored.snapshot()["allow_format_repair"])
            self.assertIs(enabled, restored.replay(0)["allow_format_repair"])
            archive["allow_format_repair"] = "false"
            with self.assertRaises(ValueError):
                Runner.from_archive(archive)

    def test_restore_rejects_tampered_roles_actions_checkpoints_and_configs(self):
        runner = Runner(configs())
        runner.step()
        archive = runner.export()
        cases = []
        changed = copy.deepcopy(archive)
        changed["game"]["players"][0]["role"] = "seer"
        cases.append(changed)
        changed = copy.deepcopy(archive)
        first_batch = changed["game"]["submitted_batches"][0]
        first_batch["actions"][next(iter(first_batch["actions"]))] = {"type": "invalid"}
        cases.append(changed)
        changed = copy.deepcopy(archive)
        changed["checkpoints"][0]["mystery"]["players"][0]["role"] = "wolf"
        cases.append(changed)
        changed = copy.deepcopy(archive)
        changed["configs"][0]["name"] = "Other name"
        cases.append(changed)
        changed = copy.deepcopy(archive)
        changed["checkpoints"].pop()
        cases.append(changed)
        for changed in cases:
            with self.subTest(case=cases.index(changed)), self.assertRaises(ValueError):
                Runner.from_archive(changed)


if __name__ == "__main__":
    unittest.main()
