"""Offline contract/integration tests; never calls a real model API."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("attributes", ROOT / "scripts/attribute_dictionary.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class AttributeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json",
                                    ROOT / "config/attribute-vocabulary.json")
        self.fixture = app.read_json(ROOT / "examples/attribute-response.json")
        self.entries = {e["category_id"]: e for e in self.fixture["entries"]}

    def job(self, *ids):
        return app.make_job(self.ctx, [self.ctx["by_id"][cid] for cid in ids])

    def payload(self, *ids):
        return {"entries": [copy.deepcopy(self.entries[cid]) for cid in ids]}

    def merge(self, *ids):
        return app.merge_response(self.payload(*ids), self.job(*ids), self.ctx,
                                  self.out, {"source": "test"})

    def test_complete_offline_flow_preserves_ids_and_resume(self):
        self.assertEqual(self.merge("airplane", "car", "fan"), 3)
        store = app.load_store(self.out, self.ctx)
        for cid, record in store["records"].items():
            self.assertEqual(record["class_index"], self.ctx["by_id"][cid]["class_index"])
            self.assertEqual(record["review_status"], "unreviewed")
        self.assertEqual(app.pending_jobs(self.ctx, self.out, ["airplane", "car", "fan"], 0, 2), [])
        summary = app.write_report(self.ctx, self.out)
        self.assertEqual(summary["generated"], 3)
        self.assertEqual(summary["missing_count"], 342)

    def test_invalid_batch_does_not_partially_write(self):
        payload = self.payload("car", "airplane")
        payload["entries"][1]["attributes"]["shape"]["tags"].append("made_up_tag")
        with self.assertRaises(ValueError):
            app.merge_response(payload, self.job("car", "airplane"), self.ctx, self.out, {})
        self.assertFalse((self.out / "dictionary.json").exists())

    def test_stored_class_index_must_match_catalog_and_be_integer(self):
        self.merge("car")
        original = app.load_store(self.out, self.ctx)
        correct = self.ctx["by_id"]["car"]["class_index"]
        for value in (9999, str(correct), float(correct), True, None):
            with self.subTest(value=value):
                store = copy.deepcopy(original)
                store["records"]["car"]["class_index"] = value
                app.write_json(self.out / "dictionary.json", store)
                with self.assertRaisesRegex(ValueError, "class_index"):
                    app.load_store(self.out, self.ctx)
        store = copy.deepcopy(original)
        del store["records"]["car"]["class_index"]
        app.write_json(self.out / "dictionary.json", store)
        with self.assertRaisesRegex(ValueError, "class_index"):
            app.load_store(self.out, self.ctx)

    def test_stored_names_must_match_catalog(self):
        self.merge("car")
        original = app.load_store(self.out, self.ctx)
        for field in ("label_en", "display_name_ko"):
            for value in ("wrong-name", None):
                with self.subTest(field=field, value=value):
                    store = copy.deepcopy(original)
                    store["records"]["car"][field] = value
                    app.write_json(self.out / "dictionary.json", store)
                    with self.assertRaisesRegex(ValueError, field):
                        app.load_store(self.out, self.ctx)

    def test_generation_rejects_mismatched_catalog_before_api_call(self):
        self.merge("car")
        store = app.load_store(self.out, self.ctx)
        store["records"]["car"]["class_index"] = 9999
        app.write_json(self.out / "dictionary.json", store)
        before = (self.out / "dictionary.json").read_bytes()
        with patch.object(app, "call_api") as api, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = app.main(["generate", "--out", str(self.out), "--model", "test-model"])
        self.assertEqual(code, 1)
        api.assert_not_called()
        self.assertEqual(before, (self.out / "dictionary.json").read_bytes())

    def test_coverage_and_duplicate_ids_rejected(self):
        for payload in (self.payload("car"), self.payload("car", "car")):
            with self.assertRaises(ValueError):
                app.validate_response(payload, self.ctx, ["car", "airplane"])

    def test_missing_module_and_illegal_empty_status_rejected(self):
        for change in ("missing", "empty_known", "uncertain_with_tags", "extra_field", "duplicate_tag"):
            payload = self.payload("car")
            entry = payload["entries"][0]
            if change == "missing":
                del entry["attributes"]["shape"]
            elif change == "empty_known":
                entry["attributes"]["shape"]["tags"] = []
            elif change == "uncertain_with_tags":
                entry["attributes"]["shape"]["status"] = "uncertain"
            elif change == "extra_field":
                entry["review_status"] = "reviewed"
            else:
                entry["attributes"]["shape"]["tags"] *= 2
            with self.subTest(change=change), self.assertRaises(ValueError):
                app.validate_response(payload, self.ctx, ["car"])

    def test_duplicate_json_keys_rejected(self):
        path = self.out / "bad.json"
        path.write_text('{"entries":[],"entries":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            app.read_json(path)

    def test_identical_import_is_idempotent(self):
        self.merge("car")
        before = (self.out / "dictionary.json").read_bytes()
        self.assertEqual(self.merge("car"), 0)
        self.assertEqual(before, (self.out / "dictionary.json").read_bytes())

    def test_reviewed_record_cannot_be_replaced_even_with_flag(self):
        self.merge("car")
        store = app.load_store(self.out, self.ctx)
        store["records"]["car"]["review_status"] = "reviewed"
        app.write_json(self.out / "dictionary.json", store)
        before = (self.out / "dictionary.json").read_bytes()
        payload = self.payload("airplane", "car")
        payload["entries"][1]["notes"] = ["수정 시도"]
        with self.assertRaises(ValueError):
            app.merge_response(payload, self.job("airplane", "car"), self.ctx, self.out, {}, True)
        self.assertEqual(before, (self.out / "dictionary.json").read_bytes())

    def test_explicit_draft_replacement_resets_to_unreviewed(self):
        self.merge("car")
        payload = self.payload("car")
        payload["entries"][0]["notes"] = ["사람이 수정할 예정인 초안"]
        with self.assertRaises(ValueError):
            app.merge_response(payload, self.job("car"), self.ctx, self.out, {})
        app.merge_response(payload, self.job("car"), self.ctx, self.out, {}, True)
        self.assertEqual(app.load_store(self.out, self.ctx)["records"]["car"]["review_status"], "unreviewed")

    def test_changed_vocabulary_cannot_mix_with_old_records_or_jobs(self):
        self.merge("car")
        updated = copy.deepcopy(self.ctx)
        updated["signatures"]["vocabulary_sha256"] = "changed"
        with self.assertRaises(ValueError):
            app.load_store(self.out, updated)
        with self.assertRaises(ValueError):
            app.check_job(self.job("car"), updated)

    def test_job_tampering_rejected(self):
        job = self.job("car")
        job["instructions"] = "Changed"
        with self.assertRaises(ValueError):
            app.check_job(job, self.ctx)

    def test_vectors_keep_coordinates_and_missing_is_null(self):
        self.merge("car", "fan")
        with self.assertRaises(ValueError):
            app.vectorize(self.ctx, self.out, False)
        app.vectorize(self.ctx, self.out, True)
        first = app.read_json(self.out / "vectors.json")
        self.assertIsNone(first["vectors"]["fan"]["shape"]["vector"])
        self.assertAlmostEqual(sum(v*v for v in first["vectors"]["car"]["shape"]["vector"]), 1)
        self.merge("giraffe")
        app.vectorize(self.ctx, self.out, True)
        second = app.read_json(self.out / "vectors.json")
        self.assertEqual(first["dimensions"], second["dimensions"])
        self.assertEqual(first["vectors"]["car"], second["vectors"]["car"])

    def test_duplicate_profiles_are_review_flags_not_auto_merges(self):
        payload = self.payload("cup", "mug")
        payload["entries"][1]["attributes"] = copy.deepcopy(payload["entries"][0]["attributes"])
        app.merge_response(payload, self.job("cup", "mug"), self.ctx, self.out, {})
        app.write_report(self.ctx, self.out)
        report = app.read_json(self.out / "review-report.json")
        self.assertEqual(len(report["identical_profiles"]), 1)
        self.assertEqual(report["generated"], 2)

    def test_api_contract_and_parser(self):
        body = app.api_payload(self.job("car"), "test-model", 1000)
        self.assertFalse(body["store"])
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        envelope = {"status": "completed", "output": [{"type": "reasoning"},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(self.payload("car"))}]}]}
        self.assertEqual(app.parse_api_response(envelope), self.payload("car"))
        for invalid in ({"status": "incomplete"}, {"status": "completed", "output": []},
                        {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}):
            with self.assertRaises(ValueError):
                app.parse_api_response(invalid)

    def test_live_command_is_bounded_and_resumable_with_mock(self):
        def fake_api(job, *_, **kwargs):
            return self.payload(*job["category_ids"]), {"source": "mock", "model": "test-model"}
        argv = ["generate", "--out", str(self.out), "--model", "test-model",
                "--categories", "airplane", "car", "giraffe", "--batch-size", "1", "--max-batches", "1"]
        with patch.object(app, "call_api", side_effect=fake_api) as api, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(argv), 0)
            first_id = api.call_args.args[0]["category_ids"][0]
            self.assertEqual(api.call_count, 1)
            self.assertEqual(app.main(argv), 0)
            second_id = api.call_args.args[0]["category_ids"][0]
            self.assertNotEqual(first_id, second_id)
        self.assertEqual(len(app.load_store(self.out, self.ctx)["records"]), 2)

    def test_dry_run_never_calls_api(self):
        with patch.object(app, "call_api") as api, contextlib.redirect_stdout(io.StringIO()):
            code = app.main(["generate", "--out", str(self.out), "--model", "test-model",
                             "--categories", "car", "--dry-run"])
        self.assertEqual(code, 0)
        api.assert_not_called()
        self.assertFalse((self.out / "dictionary.json").exists())

    def test_gms_chat_payload_and_response(self):
        body = app.api_payload(self.job("car"), "gpt-5.4-mini", 8000, "gms")
        self.assertEqual(body["model"], "gpt-5.4-mini")
        self.assertEqual(body["messages"][0]["role"], "developer")
        self.assertEqual(body["max_completion_tokens"], 8000)
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertNotIn("text", body)
        result = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.payload("car"))}}]}
        self.assertEqual(app.parse_api_response(result, "gms"), self.payload("car"))
        for reason in ("length", "content_filter", "tool_calls", None):
            result["choices"][0]["finish_reason"] = reason
            with self.assertRaises(ValueError):
                app.parse_api_response(result, "gms")
        result["choices"][0]["finish_reason"] = "stop"
        result["choices"][0]["message"]["refusal"] = "refused"
        with self.assertRaises(ValueError):
            app.parse_api_response(result, "gms")

    def test_local_key_loading_and_provider_isolation(self):
        local = self.out / ".env.local"
        local.write_text('# Local only\nGMS_KEY="test-gms"\nOPENAI_API_KEY=test-direct\n', encoding="utf-8")
        with patch.dict(app.os.environ, {}, clear=True):
            self.assertEqual(app.read_api_key("GMS_KEY", local), "test-gms")
            self.assertEqual(app.read_api_key("OPENAI_API_KEY", local), "test-direct")
        with patch.dict(app.os.environ, {"GMS_KEY": "env-priority"}, clear=True):
            self.assertEqual(app.read_api_key("GMS_KEY", local), "env-priority")
        local.write_text('OPENAI_API_KEY=test-direct\n', encoding="utf-8")
        with patch.dict(app.os.environ, {"OPENAI_API_KEY": "direct-only"}, clear=True):
            with self.assertRaisesRegex(ValueError, "GMS_KEY is missing"):
                app.read_api_key("GMS_KEY", local)

    def test_gms_transport_uses_gms_key_and_endpoint(self):
        envelope = {"id": "test-id", "usage": {"total_tokens": 10},
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.payload("car"))}}]}
        with patch.object(app, "read_api_key", return_value="test-gms") as key_loader, patch.object(app.request, "build_opener") as build:
            build.return_value.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(envelope).encode())
            payload, provenance = app.call_api(self.job("car"), "gpt-5.4-mini", 8000, 90, 0, "gms")
            key_loader.assert_called_once_with("GMS_KEY")
            sent = build.return_value.open.call_args.args[0]
            self.assertEqual(sent.full_url, app.GMS_ENDPOINT)
            self.assertEqual(sent.get_header("Authorization"), "Bearer test-gms")
            self.assertEqual(payload, self.payload("car"))
            self.assertEqual(provenance["source"], "gms_chat_completions")

    def test_gms_dry_run_never_reads_key_or_calls_api(self):
        with patch.object(app, "call_api") as api, patch.object(app, "read_api_key") as key, contextlib.redirect_stdout(io.StringIO()):
            code = app.main(["generate", "--out", str(self.out), "--provider", "gms",
                             "--model", "gpt-5.4-mini", "--categories", "car", "--dry-run"])
        self.assertEqual(code, 0)
        api.assert_not_called()
        key.assert_not_called()

    def test_v2_normalization_is_lossless_and_parent_closure_is_consistent(self):
        ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json",
                               ROOT / "config/attribute-vocabulary-v2.json")
        payload = self.payload("apple")
        payload["entries"][0]["attributes"]["classification"]["tags"] = ["fruit", "fruit"]
        fixed, changes = app.normalize_response(payload, ctx)
        self.assertEqual(payload["entries"][0]["attributes"]["classification"]["tags"], ["fruit", "fruit"])
        self.assertEqual(fixed["entries"][0]["attributes"]["classification"]["tags"], ["fruit", "food"])
        app.validate_response(fixed, ctx, ["apple"])
        self.assertTrue(changes)
        self.assertEqual(app.normalize_response(fixed, ctx), (fixed, []))
        fixed["entries"][0]["attributes"]["classification"]["tags"].append("plant")
        with self.assertRaisesRegex(ValueError, "incompatible"):
            app.validate_response(fixed, ctx, ["apple"])

    def test_v2_policy_and_contrast_peers_are_versioned(self):
        ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json",
                               ROOT / "config/attribute-vocabulary-v2.json")
        job = app.make_job(ctx, [ctx["by_id"]["apple"]])
        self.assertIn("banana", [p["category_id"] for p in job["input"]["categories"][0]["contrast_peers"]])
        self.assertNotEqual(ctx["signatures"], self.ctx["signatures"])
        app.check_job(job, ctx)

    def test_invalid_response_is_repaired_and_raw_attempts_are_retained(self):
        invalid = self.payload("car")
        invalid["entries"][0]["attributes"]["shape"]["tags"] = ["invented"]
        argv = ["generate", "--out", str(self.out), "--model", "test-model", "--categories", "car"]
        with patch.object(app, "call_api", side_effect=[(invalid, {"source": "mock"}),
                    (self.payload("car"), {"source": "mock"})]) as api, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(argv), 0)
            self.assertEqual(api.call_count, 2)
            self.assertIn("validator_feedback", api.call_args.args[0]["input"])
            app.check_job(api.call_args.args[0], self.ctx)
        self.assertEqual(len(list((self.out / "attempts").glob("*.json"))), 2)
        self.assertEqual(len(app.load_store(self.out, self.ctx)["records"]["car"]["provenance"]["attempts"]), 2)

    def test_exhausted_repair_updates_report_without_losing_completed_batch(self):
        def fake_api(job, *args, **kwargs):
            payload = self.payload(*job["category_ids"])
            if job["category_ids"] == ["car"]:
                payload["entries"][0]["attributes"]["shape"]["tags"] = ["invented"]
            return payload, {"source": "mock"}
        argv = ["generate", "--out", str(self.out), "--model", "test-model", "--categories",
                "airplane", "car", "--batch-size", "1", "--max-batches", "2"]
        with patch.object(app, "call_api", side_effect=fake_api) as api, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(app.main(argv), 1)
            self.assertEqual(api.call_count, 3)
        self.assertEqual(app.read_json(self.out / "review-report.json")["generated"], 1)
        self.assertEqual(set(app.load_store(self.out, self.ctx)["records"]), {"airplane"})

    def test_no_evidence_does_not_count_as_identical_semantics(self):
        payload = self.payload("fan", "car")
        for entry in payload["entries"]:
            for attr in entry["attributes"].values():
                attr.update(status="uncertain", tags=[])
        app.merge_response(payload, self.job("fan", "car"), self.ctx, self.out, {})
        app.write_report(self.ctx, self.out)
        report = app.read_json(self.out / "review-report.json")
        self.assertEqual(report["identical_profiles"], [])
        self.assertEqual(set(report["no_known_modules"]), {"fan", "car"})

    def test_v2_contrast_report_exposes_shared_and_distinguishing_tags(self):
        ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json",
                               ROOT / "config/attribute-vocabulary-v2.json")
        job = app.make_job(ctx, [ctx["by_id"][cid] for cid in ("apple", "banana")])
        payload = self.payload("apple", "banana")
        for entry in payload["entries"]:
            entry["attributes"]["classification"]["tags"] = ["fruit", "food"]
        app.merge_response(payload, job, ctx, self.out, {})
        app.write_report(ctx, self.out)
        report = app.read_json(self.out / "review-report.json")
        pair = report["contrast_checks"][0]
        self.assertEqual((pair["left"], pair["right"]), ("apple", "banana"))
        self.assertEqual(pair["comparable_axes"], 3)
        self.assertTrue(pair["has_tag_difference"])
        self.assertEqual(pair["axes"]["classification"]["left_only"], [])
        self.assertEqual(pair["axes"]["classification"]["right_only"], [])

    def test_compact_prompt_is_smaller_without_duplicating_tag_enums(self):
        ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json", ROOT / "config/attribute-vocabulary-v2.json")
        cats = [ctx["by_id"][cid] for cid in ("apple", "banana")]
        legacy, compact = app.make_job(ctx, cats), app.make_job(ctx, cats, "compact")
        self.assertLess(app.model_input_chars(compact), app.model_input_chars(legacy) * 0.75)
        self.assertNotIn("rounded_ears", compact["input"]["tags"]["shape"])
        schema = compact["schema"]["properties"]["entries"]["items"]["properties"]
        self.assertEqual(schema["category_id"]["enum"], ["apple", "banana"])
        self.assertNotIn("enum", schema["attributes"]["properties"]["shape"]["properties"]["tags"]["items"])
        app.check_job(compact, ctx)
        changed = copy.deepcopy(ctx)
        changed["request_config"]["version"] = "changed"
        with self.assertRaisesRegex(ValueError, "policy changed"):
            app.check_job(compact, changed)

    def test_semantic_guards_use_catalog_and_preserve_valid_metaphorical_parts(self):
        payload = self.payload("banana")
        e = payload["entries"][0]
        e["attributes"]["classification"]["tags"] = ["animal"]
        e["attributes"]["shape"]["tags"] = ["rounded_ears"]
        self.assertTrue(app.semantic_issues(e, self.ctx))  # Cannot bypass with a wrong model classification.
        for cid, tags in (("chair", ["four_legs"]), ("cello", ["long_neck"]), ("airplane", ["wings"])):
            record = copy.deepcopy(e)
            record["category_id"] = cid
            record["attributes"]["shape"]["tags"] = tags
            self.assertEqual(app.semantic_issues(record, self.ctx), [])

    def test_targeted_repair_preserves_good_entries_and_sends_only_bad_ids(self):
        def fake_api(job, *args, **kwargs):
            if len(job["category_ids"]) == 2:
                payload = self.payload("airplane", "car")
                payload["entries"][1]["attributes"]["shape"]["tags"] = ["rounded_ears"]
                return payload, {"source": "mock"}
            self.assertEqual(job["category_ids"], ["car"])
            self.assertEqual(set(app.load_store(self.out, self.ctx)["records"]), {"airplane"})
            self.assertEqual([e["category_id"] for e in job["input"]["previous_response"]["entries"]], ["car"])
            return self.payload("car"), {"source": "mock"}
        with patch.object(app, "call_api", side_effect=fake_api) as api, contextlib.redirect_stdout(io.StringIO()):
            code = app.main(["generate", "--out", str(self.out), "--model", "test-model",
                             "--categories", "airplane", "car", "--batch-size", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(api.call_count, 2)
        self.assertEqual(set(app.load_store(self.out, self.ctx)["records"]), {"airplane", "car"})

    def test_no_repair_budget_still_preserves_good_entries_for_resume(self):
        payload = self.payload("airplane", "car")
        payload["entries"][1]["attributes"]["shape"]["tags"] = ["invented"]
        with patch.object(app, "call_api", return_value=(payload, {})), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = app.main(["generate", "--out", str(self.out), "--model", "test-model",
                             "--categories", "airplane", "car", "--validation-retries", "0"])
        self.assertEqual(code, 1)
        self.assertEqual(set(app.load_store(self.out, self.ctx)["records"]), {"airplane"})
        pending = app.pending_jobs(self.ctx, self.out, ["airplane", "car"], 0, 10, "compact")
        self.assertEqual(pending[0]["category_ids"], ["car"])

    def test_flagged_selection_never_retags_clean_or_reviewed_records(self):
        payload = self.payload("car", "airplane")
        payload["entries"][0]["attributes"]["shape"]["tags"].append("rounded_ears")
        app.merge_response(payload, self.job("car", "airplane"), self.ctx, self.out, {})
        before = (self.out / "dictionary.json").read_bytes()
        jobs = app.pending_jobs(self.ctx, self.out, None, 0, 10, "compact", "flagged")
        self.assertEqual(jobs[0]["category_ids"], ["car"])
        app.write_report(self.ctx, self.out)
        self.assertEqual((self.out / "dictionary.json").read_bytes(), before)
        data = app.load_store(self.out, self.ctx)
        data["records"]["car"]["review_status"] = "reviewed"
        app.write_json(self.out / "dictionary.json", data)
        self.assertEqual(app.pending_jobs(self.ctx, self.out, None, 0, 10, "compact", "flagged"), [])

    def test_http_call_cap_counts_retries_and_blocks_before_key_on_exhaustion(self):
        budget = {"used": 0, "limit": 1}
        failure = app.error.HTTPError(app.GMS_ENDPOINT, 429, "limited", {}, None)
        with patch.object(app, "read_api_key", return_value="dummy"), patch.object(app.request, "build_opener") as build, patch.object(app.time, "sleep"):
            build.return_value.open.side_effect = failure
            with self.assertRaisesRegex(ValueError, "call limit"):
                app.call_api(self.job("car"), "test-model", 100, 10, 3, "gms", budget)
            self.assertEqual(build.return_value.open.call_count, 1)
            self.assertEqual(budget["used"], 1)
        with patch.object(app, "read_api_key") as key:
            with self.assertRaisesRegex(ValueError, "call limit"):
                app.call_api(self.job("car"), "test-model", 100, 10, 3, "gms", budget)
            key.assert_not_called()

    def test_compact_output_limits_and_manual_import_guard(self):
        job = app.make_job(self.ctx, [self.ctx["by_id"]["car"]], "compact")
        payload = self.payload("car")
        payload["entries"][0]["attributes"]["shape"]["description_ko"] = "x" * 61
        with self.assertRaisesRegex(ValueError, "description exceeds"):
            app.merge_response(payload, job, self.ctx, self.out, {})
        self.assertFalse((self.out / "dictionary.json").exists())

    def test_usage_counts_requests_not_record_provenance_copies(self):
        self.merge("car", "airplane")
        app.write_json(self.out / "attempts" / "one.json", {"provenance": {"usage": {
            "prompt_tokens": 50, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 10}}}})
        summary = app.usage_summary(self.out)
        self.assertEqual(summary["recorded_responses"], 1)
        self.assertEqual(summary["input_tokens"], 50)
        self.assertEqual(summary["output_tokens"], 20)
        self.assertEqual(summary["cached_input_tokens"], 10)

    def test_v3_uses_its_own_guard_rules_and_tree_closure(self):
        v2 = app.load_context(ROOT / "data/quickdraw/metadata/labels.json", ROOT / "config/attribute-vocabulary-v2.json")
        v3 = app.load_context(ROOT / "data/quickdraw/metadata/labels.json", ROOT / "config/attribute-vocabulary-v3.json")
        self.assertEqual(v2["request_config"]["version"], "compact-request-v1")
        self.assertEqual(v3["request_config"]["version"], "compact-request-v3.1")
        self.assertNotEqual(v2["signatures"], v3["signatures"])
        record = {"category_id": "chair", "notes": [], "attributes": {
            "classification": {"status": "known", "tags": ["seating"], "description_ko": "x"},
            "shape": {"status": "known", "tags": ["long_ears"], "description_ko": "x"},
            "function": {"status": "known", "tags": ["eating"], "description_ko": "x"}}}
        self.assertEqual(len(app.semantic_issues(record, v3)), 2)
        fixed, _ = app.normalize_response({"entries": [record]}, v3)
        self.assertEqual(fixed["entries"][0]["attributes"]["classification"]["tags"],
                         ["seating", "furniture", "artifact"])
        fixed["entries"][0]["attributes"]["classification"]["tags"].append("organism")
        with self.assertRaisesRegex(ValueError, "incompatible"):
            app.validate_response(fixed, v3, ["chair"])

    def test_v3_manual_import_rejects_siblings_without_writing(self):
        ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json",
                               ROOT / "config/attribute-vocabulary-v3.json")
        record = app.read_json(ROOT / "data/attributes/draft-v3/dictionary.json")["records"]["cat"]
        entry = {k: copy.deepcopy(record[k]) for k in ("category_id", "attributes", "notes")}
        entry["attributes"]["classification"]["tags"] = ["feline", "canine"]
        payload, _ = app.normalize_response({"entries": [entry]}, ctx)
        for profile in ("legacy", "compact"):
            with self.subTest(profile=profile):
                job = app.make_job(ctx, [ctx["by_id"]["cat"]], profile)
                with self.assertRaisesRegex(ValueError, "single classification path"):
                    app.merge_response(payload, job, ctx, self.out, {"source": "test"})
                self.assertFalse((self.out / "dictionary.json").exists())
        entry["attributes"]["classification"]["tags"] = ["feline"]
        payload, _ = app.normalize_response({"entries": [entry]}, ctx)
        self.assertEqual(app.merge_response(payload, job, ctx, self.out, {"source": "test"}), 1)

    def test_single_path_rule_is_opt_in_and_legacy_stores_still_load(self):
        for version, vocabulary in ((1, "attribute-vocabulary.json"), (2, "attribute-vocabulary-v2.json")):
            with self.subTest(version=version):
                ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json", ROOT / "config" / vocabulary)
                self.assertNotIn("classification", ctx["request_config"].get("single_path_modules", []))
                self.assertTrue(app.load_store(ROOT / f"data/attributes/draft-v{version}", ctx)["records"])

    def test_v3_whole_dictionary_obeys_single_path_rule(self):
        ctx = app.load_context(ROOT / "data/quickdraw/metadata/labels.json",
                               ROOT / "config/attribute-vocabulary-v3.json")
        self.assertEqual(len(app.load_store(ROOT / "data/attributes/draft-v3", ctx)["records"]), 345)


if __name__ == "__main__":
    unittest.main()
