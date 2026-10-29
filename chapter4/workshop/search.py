"""外部API不要の文字n-gram TF-IDFベクトル検索。意味埋め込みではない。"""
import csv
import json
import math
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

from langchain_core.tools import tool
from pypdf import PdfReader

from src.models import SearchOutput
from workshop.embeddings import LocalEmbeddings, normalize
from src.security import read_json, MAX_QUERY_CHARS, safe_dir, write_json_atomic
import hashlib

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / ".workshop" / "documents.json"
VECTOR_INDEX = ROOT / ".workshop" / "embeddings.json"


def verify_corpus():
    manifest = read_json(ROOT / "workshop" / "corpus-manifest.json", 16384)
    folder = ROOT / "data"
    files = [p for p in folder.iterdir() if p.suffix.lower() in {".pdf", ".csv"}]
    if {path.name for path in files} != set(manifest):
        raise ValueError("検索資料は配布物に同梱したPDF・CSVに限定しています")
    for path in files:
        if path.is_symlink() or path.is_junction() or path.resolve().parent != folder.resolve() or path.stat().st_size > 5*1024*1024:
            raise ValueError("検索資料のパスまたはサイズが不正です")
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[path.name]:
            raise ValueError("同梱資料の内容が変わっています。未確認の資料は読み込めません")


def tokens(text):
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower())
    return [text[i:i+n] for n in (2, 3) for i in range(len(text)-n+1)]


def build_index(settings=None):
    verify_corpus()
    docs = []
    for path in sorted((ROOT / "data").glob("*.pdf")):
        reader = PdfReader(path)
        if len(reader.pages) > 100:
            raise ValueError("PDFのページ数上限を超えています")
        for page_no, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if len(text) > 100000:
                raise ValueError("PDFページのテキスト量が上限を超えています")
            for start in range(0, len(text), 600):
                chunk = text[start:start+700].strip()
                if chunk:
                    docs.append({"kind": "manual", "file_name": f"{path.name} p.{page_no}", "content": chunk})
    with (ROOT / "data" / "XYZ_system_QA.csv").open(encoding="utf-8-sig", newline="") as f:
        for row_no, row in enumerate(csv.DictReader(f), 2):
            docs.append({"kind": "qa", "file_name": f"XYZ_system_QA.csv row {row_no}", "content": f"質問: {row['Q']}\n回答: {row['A']}"})
    if not docs:
        raise ValueError("検索対象の文書がありません")
    if len(docs) > 1000 or any(len(doc["content"]) > 4096 for doc in docs):
        raise ValueError("検索資料の件数またはテキスト量が上限を超えています")
    write_json_atomic(INDEX, docs, ROOT)
    counts = Counter(doc["kind"] for doc in docs)
    if settings is not None and settings.search_backend == "lmstudio":
        embeddings = LocalEmbeddings(settings)
        try:
            vectors = []
            for start in range(0, len(docs), settings.embedding_batch_size):
                batch = docs[start:start+settings.embedding_batch_size]
                vectors.extend(embeddings.embed([doc["content"] for doc in batch]))
                logging.info("EMBEDDING_INDEX model=%s documents=%d/%d", settings.embedding_model, len(vectors), len(docs))
            if len({len(v) for v in vectors}) != 1:
                raise ValueError("文書Embeddingの次元数が一致しません")
            data = {"signature": embeddings.signature(docs), "vectors": vectors, "api_calls": embeddings.calls}
            write_json_atomic(VECTOR_INDEX, data, ROOT)
            counts["embedding_vectors"] = len(vectors)
        finally:
            embeddings.close()
    return counts


class LocalSearch:
    def __init__(self, settings=None):
        safe_dir(ROOT / ".workshop", ROOT)
        verify_corpus()
        if not INDEX.exists():
            raise ValueError("先にpython -m workshop indexを実行してください")
        self.docs = read_json(INDEX, 4*1024*1024)
        if not isinstance(self.docs, list) or not 1 <= len(self.docs) <= 1000:
            raise ValueError("文書キャッシュの件数が不正です")
        for doc in self.docs:
            if not isinstance(doc, dict) or doc.get("kind") not in {"qa", "manual"}:
                raise ValueError("文書キャッシュの形式が不正です")
            SearchOutput.model_validate({"file_name": doc.get("file_name"), "content": doc.get("content")})
        self.embeddings = None
        self.query_calls = 0
        if settings is not None and settings.search_backend == "lmstudio":
            self.embeddings = LocalEmbeddings(settings)
            try:
                if not VECTOR_INDEX.exists():
                    raise ValueError("Embedding用の「検索データを準備」を先に実行してください")
                stored = read_json(VECTOR_INDEX, 32*1024*1024)
                if stored["signature"] != self.embeddings.signature(self.docs):
                    raise ValueError("文書またはEmbedding設定が変わっています。「検索データを準備」をやり直してください")
                self.vectors = [normalize(vector) for vector in stored["vectors"]]
                if len(self.vectors) != len(self.docs) or len({len(v) for v in self.vectors}) != 1:
                    raise ValueError("Embeddingインデックスが不正です。検索データを準備し直してください")
            except Exception:
                self.embeddings.close()
                raise
            return
        counts = [Counter(tokens(doc["content"])) for doc in self.docs]
        df = Counter(term for count in counts for term in count)
        self.idf = {term: math.log((1+len(counts))/(1+freq))+1 for term, freq in df.items()}
        self.vectors = [self.vector(count) for count in counts]

    def vector(self, count):
        vec = {term: (1+math.log(freq))*self.idf[term] for term, freq in count.items() if term in self.idf}
        norm = math.sqrt(sum(v*v for v in vec.values())) or 1
        return {term: value/norm for term, value in vec.items()}

    def search(self, query, kind, limit=3):
        if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS or kind not in {"manual", "qa"}:
            raise ValueError("検索条件の形式またはサイズが不正です")
        if not query.strip():
            return []
        if self.embeddings:
            vec = self.embeddings.embed([query], query=True)[0]
            self.query_calls += 1
            if len(vec) != len(self.vectors[0]):
                raise ValueError("検索語と文書のEmbedding次元が異なります。検索データを準備し直してください")
            score = lambda stored: sum(a*b for a, b in zip(vec, stored))
        else:
            vec = self.vector(Counter(tokens(query)))
            score = lambda stored: sum(v*stored.get(t, 0) for t, v in vec.items())
        ranked = sorted(((score(stored), doc)
                         for stored, doc in zip(self.vectors, self.docs) if doc["kind"] == kind),
                        key=lambda item: item[0], reverse=True)
        return [SearchOutput(file_name=doc["file_name"], content=doc["content"])
                for score, doc in ranked[:limit] if score > 0]

    def close(self):
        if self.embeddings:
            self.embeddings.close()

    def tools(self):
        @tool
        def search_xyz_manual(keywords: str) -> list[SearchOutput]:
            """XYZシステムのマニュアルとリリースノートを検索。固有名詞やエラーコードを短く指定。"""
            return self.search(keywords, "manual")

        @tool
        def search_xyz_qa(query: str) -> list[SearchOutput]:
            """XYZシステムの過去のQAから具体的な設定手順やトラブル対処例を検索。短い検索語を指定。"""
            return self.search(query, "qa")

        return [search_xyz_manual, search_xyz_qa]
