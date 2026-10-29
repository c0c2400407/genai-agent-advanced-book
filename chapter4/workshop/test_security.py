import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from src.agent import HelpDeskAgent
from src.configs import Settings
from src.llm import LLM
from src.security import (
    BoundedTransport,
    endpoint,
    query_arguments,
    read_json,
    reveal,
    validate_question,
    redact,
    RedactingFormatter,
)
from src.security import ensure_runtime
from workshop.search import LocalSearch, build_index
from workshop.service import execute


class SecurityTests(unittest.TestCase):
    def test_runtime_openssl_patch_version_is_checked(self):
        with patch("src.security.ssl.OPENSSL_VERSION_INFO", (3, 5, 0, 9, 0)):
            ensure_runtime()
        with patch("src.security.ssl.OPENSSL_VERSION_INFO", (3, 5, 0, 8, 0)), self.assertRaises(RuntimeError):
            ensure_runtime()

    def test_endpoint_blocks_plaintext_remote_userinfo_and_ambiguous_urls(self):
        invalid = [
            "http://openrouter.ai/api/v1",
            "https://openrouter.ai.evil.test/api/v1",
            "https://key@openrouter.ai/api/v1",
            "https://openrouter.ai/api/v1?key=secret",
            "https://openrouter.ai:444/api/v1",
            "http://localhost:1234/v1#x",
            "http://169.254.169.254/v1",
            "http://127.0.0.1:1234/other",
            "http://localhost:1234/v1\n",
            "http://evil.test/?openrouter.ai",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                endpoint(value)
        self.assertEqual(endpoint("http://localhost:1234/v1/"), ("http://127.0.0.1:1234/v1", False))
        with self.assertRaises(ValueError):
            endpoint("https://openrouter.ai/api/v1", local_only=True)

    def test_transport_bounds_response_and_rejects_compression(self):
        for headers, content in [({}, b"0123456789"), ({"content-encoding": "gzip"}, b"fake")]:
            transport = BoundedTransport(
                httpx.MockTransport(
                    lambda request: httpx.Response(200, headers=headers, stream=httpx.ByteStream(content))
                ),
                limit=5,
            )
            with httpx.Client(transport=transport) as client, self.assertRaises(httpx.ReadError):
                client.get("http://127.0.0.1/test")

    def test_requests_do_not_follow_redirects(self):
        sent = []

        def handle(request):
            sent.append(str(request.url))
            return httpx.Response(307, headers={"location": "https://evil.test/steal"})

        with httpx.Client(transport=BoundedTransport(httpx.MockTransport(handle)), follow_redirects=False) as client:
            self.assertEqual(client.post("http://127.0.0.1/test", content=b"private").status_code, 307)
        self.assertEqual(len(sent), 1)

    def test_key_repr_validation_and_error_response_are_redacted(self):
        key = "sk-or-v1-" + "x" * 64
        settings = Settings(
            _env_file=None, openai_api_key=key, openai_model="test-local", openai_api_base="http://localhost:1234/v1"
        )
        self.assertNotIn(key, repr(settings))
        self.assertNotIn(key, redact("Bearer " + key, [settings.openai_api_key]))
        with self.assertRaises(ValueError) as error:
            Settings(_env_file=None, openai_api_key=key, max_subtasks=key)
        self.assertNotIn(key, str(error.exception))
        client = OpenAI(
            api_key=key,
            base_url="http://localhost:1234/v1",
            max_retries=0,
            http_client=httpx.Client(
                transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": key}}))
            ),
        )
        llm = LLM(settings, client=client)
        with self.assertRaises(RuntimeError) as error:
            llm.complete(model="test-local", messages=[{"role": "user", "content": "test"}])
        self.assertNotIn(key, str(error.exception))
        self.assertIn("401", str(error.exception))
        llm.close()

    def test_argument_and_question_limits(self):
        for raw in [
            '{"query":"a","query":"b"}',
            '{"query":{"file":"secret"}}',
            '{"query":"a","url":"http://evil"}',
            json.dumps({"query": "a" * 257}),
        ]:
            with self.assertRaises(ValueError):
                query_arguments(raw, {"query"})
        with self.assertRaises(ValueError):
            validate_question("x" * 4001)

    def test_untrusted_tool_names_and_batch_are_rejected_before_execution(self):
        settings = Settings(_env_file=None, openai_model="test-local", openai_api_base="http://localhost:1234/v1")
        with patch("src.agent.LLM"):
            agent = HelpDeskAgent(settings, tools=LocalSearch().tools())
        malicious = {
            "id": "1",
            "type": "function",
            "function": {"name": "os.system", "arguments": '{"command":"anything"}'},
        }
        valid = {"id": "1", "type": "function", "function": {"name": "search_xyz_qa", "arguments": '{"query":"認証"}'}}
        for calls in [[malicious], [valid] * 3, [valid, valid]]:
            with self.assertRaises(ValueError):
                agent.steps.validate_calls(calls)

    def test_remote_model_cannot_change_after_construction(self):
        settings = Settings(_env_file=None, openai_model="vendor/model:free", openai_api_key="fake")
        llm = LLM(settings, client=Mock())
        with self.assertRaises(ValueError):
            llm.complete(model="vendor/paid")
        self.assertEqual(llm.calls, 0)

    def test_oversized_json_and_modified_corpus_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test.json"
            path.write_text('"1234567890"', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_json(path, 4)
            (root / "data").mkdir()
            (root / "workshop").mkdir()
            (root / "data/x.pdf").write_bytes(b"changed")
            (root / "workshop/corpus-manifest.json").write_text('{"x.pdf":"wrong hash"}', encoding="utf-8")
            with patch("workshop.search.ROOT", root), patch("workshop.search.PdfReader") as reader:
                with self.assertRaises(ValueError):
                    build_index()
                reader.assert_not_called()

    def test_opt_out_saved_result_omits_private_question_and_answer(self):
        import logging

        key = "sk-or-v1-" + "a" * 64
        settings = Settings(
            _env_file=None,
            openai_model="test-local",
            openai_api_base="http://localhost:1234/v1",
            openai_api_key=key,
            save_full_logs=False,
        )
        fake_agent = Mock()
        fake_agent.llm.calls = 5
        fake_agent.run_agent.return_value.model_dump.return_value = {
            "question": "private question",
            "answer": "private answer " + key,
            "subtasks": [{"is_completed": True}],
            "plan": {"subtasks": ["private plan"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workshop").mkdir()
            with (
                patch("workshop.service.ROOT", root),
                patch("workshop.service.require_loaded_model", return_value=None),
                patch("workshop.service.LocalSearch") as search,
                patch("workshop.service.HelpDeskAgent", return_value=fake_agent),
            ):
                search.return_value.query_calls = 0
                result, path = execute(settings, "run", "private question")
                saved = path.read_text(encoding="utf-8")
        self.assertNotIn("private question", saved)
        self.assertNotIn("private answer", saved)
        self.assertNotIn(key, saved)
        self.assertNotIn(key, result["answer"])
        self.assertFalse(json.loads(saved)["content_saved"])

    def test_default_logging_keeps_diagnostics_and_masks_keys_on_success_and_failure(self):
        key = "sk-or-v1-" + "b" * 64
        settings = Settings(
            _env_file=None, openai_model="test-local", openai_api_base="http://localhost:1234/v1", openai_api_key=key
        )
        self.assertTrue(settings.save_full_logs)
        for failure in [False, True]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "workshop").mkdir()
                agent = Mock()
                agent.llm.calls = 2
                agent.run_agent.return_value.model_dump.return_value = {
                    "question": "diagnostic question",
                    "answer": "answer " + key,
                    "plan": {"subtasks": ["investigate"]},
                    "subtasks": [{"is_completed": True}],
                }
                if failure:
                    agent.run_agent.side_effect = RuntimeError("failed " + key)
                with (
                    patch("workshop.service.ROOT", root),
                    patch("workshop.service.require_loaded_model", return_value=None),
                    patch("workshop.service.LocalSearch") as search,
                    patch("workshop.service.HelpDeskAgent", return_value=agent),
                ):
                    search.return_value.query_calls = 0
                    result, path = execute(settings, "run", "diagnostic question")
                saved = path.read_text(encoding="utf-8")
                record = json.loads(saved)
                self.assertTrue(record["content_saved"])
                self.assertEqual(record["question"], "diagnostic question")
                self.assertNotIn(key, saved)
                self.assertNotIn(key, path.with_suffix(".log").read_text(encoding="utf-8"))
                if failure:
                    self.assertEqual(record["status"], "error")
                    self.assertEqual(record["error_type"], "RuntimeError")
                    self.assertTrue(record["error_location"])
                else:
                    self.assertIn("answer", record)
                    self.assertIn("plan", record)
