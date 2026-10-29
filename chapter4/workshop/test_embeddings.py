import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from src.configs import Settings
from workshop.embeddings import LocalEmbeddings, normalize
from workshop.search import LocalSearch


class EmbeddingTests(unittest.TestCase):
    def settings(self):
        return Settings(_env_file=None, search_backend="lmstudio", embedding_model="text-embedding-nomic-embed-text-v1.5")

    def test_local_api_prefixes_normalization_and_response_order(self):
        sent = []

        def handle(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"object": "list", "model": "test", "data": [
                {"index": 1, "object": "embedding", "embedding": [0.0, 2.0]},
                {"index": 0, "object": "embedding", "embedding": [3.0, 0.0]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1}})

        client = OpenAI(api_key="test", base_url="http://localhost:1234/v1",
                        http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        with patch("workshop.embeddings.require_embedding_model"):
            embeddings = LocalEmbeddings(self.settings(), client=client)
        self.assertEqual(embeddings.embed(["文書A", "文書B"]), [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(sent[0]["input"], ["search_document: 文書A", "search_document: 文書B"])
        self.assertEqual(embeddings.prefix(query=True), "search_query: ")
        embeddings.close()

    def test_invalid_vectors_are_rejected(self):
        for vector in [[], [0, 0], [float("nan"), 1], [float("inf"), 0]]:
            with self.assertRaises(ValueError):
                normalize(vector)

    def test_cached_vectors_use_same_model_and_rank_by_cosine(self):
        docs = [{"kind": "qa", "file_name": "A", "content": "認証手順"},
                {"kind": "qa", "file_name": "B", "content": "通知設定"}]
        fake = Mock()
        signature = {"model": "test", "corpus_sha256": "same"}
        fake.signature.return_value = signature
        fake.embed.return_value = [[0.0, 1.0]]
        with tempfile.TemporaryDirectory() as tmp:
            index, vectors = Path(tmp)/"docs.json", Path(tmp)/"vectors.json"
            index.write_text(json.dumps(docs), encoding="utf-8")
            vectors.write_text(json.dumps({"signature": signature, "vectors": [[1, 0], [0, 2]]}), encoding="utf-8")
            with patch("workshop.search.INDEX", index), patch("workshop.search.VECTOR_INDEX", vectors), patch("workshop.search.LocalEmbeddings", return_value=fake):
                search = LocalSearch(self.settings())
                self.assertEqual(search.search("通知", "qa")[0].file_name, "B")
                self.assertEqual(search.query_calls, 1)
                fake.embed.assert_called_with(["通知"], query=True)
                search.close()
                fake.signature.return_value = {"model": "different"}
                with self.assertRaisesRegex(ValueError, "設定が変わって"):
                    LocalSearch(self.settings())

    def test_chat_model_cannot_be_used_as_embedding(self):
        from workshop.checks import require_embedding_model
        response = httpx.Response(200, request=httpx.Request("GET", "http://localhost:1234/api/v0/models"),
            json={"data": [{"id": self.settings().embedding_model, "type": "llm", "state": "loaded"}]})
        with patch("workshop.checks.fetch_models", return_value=response.json()["data"]), self.assertRaises(ValueError):
            require_embedding_model(self.settings())
