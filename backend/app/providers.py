"""Providers never call a paid API in demo/local mode."""
import hashlib
import json
import math
import re

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from .config import ROOT, settings
from .schemas import Analysis, SolutionData, Statement, TagAnalysis


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
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            return schema.model_validate_json(content)
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
            solution.tags = [allowed[normalize(t)] for t in solution.tags]
            solution.free_tags = []
            solution.source = "llm"
            solution.trusted = False
        return result


class Embedder:
    @property
    def identity(self):
        model = "hash-v1" if settings.embedding_provider == "local" else settings.embedding_model
        return f"{settings.embedding_provider}:{model}:{settings.embedding_dimensions}"

    def embed(self, document):
        if settings.embedding_provider == "api":
            if not settings.embedding_base_url or not settings.embedding_model:
                raise HTTPException(503, "Укажите EMBEDDING_BASE_URL и EMBEDDING_MODEL")
            try:
                response = httpx.post(
                    settings.embedding_base_url.rstrip("/") + "/embeddings",
                    headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
                    json={"model": settings.embedding_model, "input": document},
                    timeout=settings.llm_timeout,
                )
                response.raise_for_status()
                vector = [float(v) for v in response.json()["data"][0]["embedding"]]
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                raise HTTPException(502, "Не удалось получить эмбеддинг") from exc
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
