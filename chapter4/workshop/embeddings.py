"""LM StudioのローカルEmbedding API。文書と検索語で同じモデル・正規化を使う。"""
import hashlib
import json
import math

from openai import OpenAI

from workshop.checks import require_embedding_model
from src.security import endpoint, http_client, public_error, reveal


def normalize(vector):
    if not isinstance(vector, list) or not 1 <= len(vector) <= 8192 or not all(type(x) in {int, float} and math.isfinite(x) for x in vector):
        raise ValueError("Embeddingベクトルが空または不正です")
    length = math.sqrt(sum(x*x for x in vector))
    if length == 0:
        raise ValueError("Embeddingベクトルの長さが0です")
    return [x/length for x in vector]


def fingerprint(docs):
    return hashlib.sha256(json.dumps(docs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class LocalEmbeddings:
    def __init__(self, settings, client=None):
        require_embedding_model(settings)
        self.settings = settings
        self.calls = 0
        base, _remote = endpoint(settings.embedding_base_url, local_only=True)
        self.client = client or OpenAI(base_url=base,
            api_key=reveal(settings.embedding_api_key), max_retries=0, timeout=180, http_client=http_client())

    def prefix(self, query=False):
        value = self.settings.embedding_query_prefix if query else self.settings.embedding_document_prefix
        if value != "auto":
            return value
        if "nomic-embed-text-v1.5" in self.settings.embedding_model.lower():
            return "search_query: " if query else "search_document: "
        return ""

    def signature(self, docs):
        return {"corpus_sha256": fingerprint(docs), "model": self.settings.embedding_model,
                "base_url": self.settings.embedding_base_url.rstrip("/"),
                "document_prefix": self.prefix(), "query_prefix": self.prefix(query=True)}

    def embed(self, texts, query=False):
        if not isinstance(texts, list) or not 1 <= len(texts) <= 64 or any(not isinstance(t, str) or len(t) > 8192 for t in texts):
            raise ValueError("Embedding入力の件数またはサイズが不正です")
        self.calls += 1
        try:
            response = self.client.embeddings.create(model=self.settings.embedding_model,
                input=[self.prefix(query=query)+text.replace("\n", " ") for text in texts], encoding_format="float")
        except Exception as exc:
            raise RuntimeError(public_error(exc, [self.settings.embedding_api_key])) from None
        data = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in data] != list(range(len(texts))):
            raise ValueError("Embedding応答の件数または順番が不正です")
        vectors = [normalize(item.embedding) for item in data]
        if len({len(vector) for vector in vectors}) != 1:
            raise ValueError("Embeddingの次元数が一致しません")
        return vectors

    def close(self):
        self.client.close()
