"""Providers never call a paid API in demo/local mode."""
import hashlib
import json
import logging
import math
import re
from functools import lru_cache
from threading import Lock

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from .config import ROOT, settings
from .schemas import Analysis, SolutionData, Statement, TagAnalysis

_local_model_lock = Lock()


@lru_cache(maxsize=1)
def _local_model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=settings.embedding_local_model,
                         cache_dir=settings.embedding_cache_dir,
                         threads=settings.embedding_threads)


def _embedding_chunks(document, model):
    # Stay below MiniLM's 128-token window, including special tokens. Counting
    # also catches non-Latin text, where a character limit alone loses content.
    if model.token_count(document) <= 112:
        yield document
        return
    middle = len(document) // 2
    boundary = document.rfind(" ", middle // 2, middle + 1)
    if boundary < 1:
        boundary = middle
    yield from _embedding_chunks(document[:boundary], model)
    yield from _embedding_chunks(document[boundary:], model)


def _embedding_text(value):
    # JSON field names, booleans and empty defaults overwhelm small sentence
    # models. Index the actual content of the same structured document.
    if isinstance(value, dict):
        return "\n".join(_embedding_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_embedding_text(item) for item in value)
    return value if isinstance(value, str) else ""


def _local_vector(model, document, query=False):
    chunks = _embedding_chunks(document, model)
    vectors = (model.query_embed(chunks, batch_size=32) if query
               else model.passage_embed(chunks, batch_size=32))
    total = None
    for row in vectors:
        length = math.sqrt(sum(float(value) ** 2 for value in row))
        if not length or not math.isfinite(length):
            raise ValueError("Invalid local embedding")
        unit = [float(value) / length for value in row]
        total = unit if total is None else [a + b for a, b in zip(total, unit)]
    length = math.sqrt(sum(value ** 2 for value in total))
    return [value / length for value in total]


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


class Analyzer:
    def _chat(self, prompt, payload, schema):
        if not settings.llm_api_key:
            raise HTTPException(503, "Укажите LLM_API_KEY для обращения к LLM")
        try:
            response = httpx.post(
                settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={"model": settings.llm_model, "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ], "temperature": 0, "max_tokens": settings.llm_max_tokens},
                timeout=settings.llm_timeout,
            )
            if not response.is_success:
                raise HTTPException(502, f"LLM Gateway вернула HTTP {response.status_code}. Проверьте доступность модели и квоту.")
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise HTTPException(502, "LLM исчерпала лимит ответа. Увеличьте LLM_MAX_TOKENS или выберите модель без длинного рассуждения.")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty LLM content")
            content = content.strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            return schema.model_validate_json(content)
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "LLM не ответила за отведённое время. Изменения не сохранены.") from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            # Never include remote response bodies or credentials in API errors.
            raise HTTPException(502, "LLM не вернула корректный JSON. Изменения не сохранены.") from exc

    def analyze(self, title, statement, solutions, tags):
        if settings.llm_provider == "demo":
            # Preserve inputs; do not pretend to infer an algorithm without a model.
            return Analysis(
                statement=Statement(canonical_name=title, abstract=statement, task=title),
                solutions=[SolutionData.model_validate(s) for s in solutions],
            )
        prompt = (ROOT / "prompts/analyze.md").read_text(encoding="utf-8")
        prompt = prompt.replace("<TAG_LIST>", json.dumps(tags, ensure_ascii=False))
        result = self._chat(prompt, {"title": title, "statement": statement, "solutions": solutions}, Analysis)
        coded_inputs = [i for i, s in enumerate(solutions) if s.get("code")]
        if coded_inputs and len(result.solutions) <= max(coded_inputs) and not result.statement.image_required:
            raise HTTPException(502, "LLM пропустила решение с кодом. Сопоставление по порядку невозможно.")
        return result

    def check_tags(self, statement, solutions, tags):
        if settings.llm_provider == "demo":
            raise HTTPException(409, "Проверка применимости новых тегов требует LLM_PROVIDER=gateway и ключа")
        prompt = (ROOT / "prompts/reindex_tags.md").read_text(encoding="utf-8")
        prompt = prompt.replace("<TAG_LIST>", json.dumps(tags, ensure_ascii=False))
        result = self._chat(prompt, {"statement": statement, "solutions": solutions}, TagAnalysis)
        allowed = {normalize(t): t for t in tags}
        for solution in result.solutions:
            if not solution.tags or any(normalize(t) not in allowed for t in solution.tags):
                raise HTTPException(502, "LLM вернула теги вне проверяемого списка")
            if not solution.complexity.time or not solution.complexity.memory:
                raise HTTPException(502, "LLM не указала асимптотику нового решения")
            if solution.difficulty is None:
                raise HTTPException(502, "LLM не указала сложность нового решения")
            solution.tags = [allowed[normalize(t)] for t in solution.tags]
            solution.free_tags = []
            solution.source = "llm"
            solution.trusted = False
        return result


class Embedder:
    @property
    def identity(self):
        if settings.embedding_provider == "hash":
            model = "hash-v1"
        elif settings.embedding_provider == "local":
            model = settings.embedding_local_model + ":content-v2"
        else:
            model = settings.embedding_base_url.rstrip("/") + ":" + settings.embedding_model
        return f"{settings.embedding_provider}:{model}:{settings.embedding_dimensions}"

    def embed(self, document, *, query=False):
        if settings.embedding_provider == "api":
            if not settings.embedding_base_url or not settings.embedding_model:
                raise HTTPException(503, "Укажите EMBEDDING_BASE_URL и EMBEDDING_MODEL")
            try:
                response = httpx.post(
                    settings.embedding_base_url.rstrip("/") + "/embeddings",
                    headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
                    json={"model": settings.embedding_model, "input": document,
                          "dimensions": settings.embedding_dimensions},
                    timeout=settings.llm_timeout,
                )
                response.raise_for_status()
                vector = [float(v) for v in response.json()["data"][0]["embedding"]]
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                raise HTTPException(502, "Не удалось получить эмбеддинг") from exc
        elif settings.embedding_provider == "local":
            try:
                with _local_model_lock:
                    model = _local_model()
                if query:
                    vector = _local_vector(model, document, query=True)
                else:
                    payload = json.loads(document)
                    vector = [2 * value for value in _local_vector(model, _embedding_text(payload))]
                    # Preserve the full analysis while giving the task's intent
                    # equal weight, regardless of how many solutions it has.
                    for field, weight in [("canonical_name", 1), ("abstract", 0.5), ("task", 0.5)]:
                        if content := payload.get("statement", {}).get(field):
                            focus = _local_vector(model, content)
                            vector = [a + weight * b for a, b in zip(vector, focus)]
            except Exception as exc:
                logging.getLogger(__name__).exception("Local embedding failed")
                raise HTTPException(503, "Локальная модель эмбеддингов недоступна. Проверьте загрузку модели и журнал backend.") from exc
        else:
            # Offline lexical baseline. Not a substitute for semantic embeddings.
            vector = [0.0] * settings.embedding_dimensions
            words = re.findall(r"[\w]+", normalize(document))
            features = words + [w[i:i + 3] for w in words for i in range(max(0, len(w) - 2))]
            for feature in features:
                digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
                vector[int.from_bytes(digest[:4], "little") % len(vector)] += 1 if digest[4] % 2 else -1
        if len(vector) != settings.embedding_dimensions or not all(math.isfinite(v) for v in vector):
            raise HTTPException(502, "Размерность или значения эмбеддинга не соответствуют настройкам")
        length = math.sqrt(sum(v * v for v in vector))
        if length == 0:
            raise HTTPException(502, "Модель вернула нулевой эмбеддинг")
        return [v / length for v in vector]


class QueryEnricher:
    def process(self, query):
        return query


class Reranker:
    def process(self, results):
        return results


analyzer = Analyzer()
embedder = Embedder()
query_enricher = QueryEnricher()
reranker = Reranker()
