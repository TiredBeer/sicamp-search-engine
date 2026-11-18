import json
import re
from datetime import timezone
from threading import RLock

from fastapi import HTTPException
from sqlalchemy import select

from .config import ROOT
from .db import FreeTag, Problem, SearchRecord, Solution, Tag, now
from .providers import embedder, normalize
from .schemas import SolutionData

# One API process (one uvicorn worker), matching the two-container deployment.
# Serialize write transactions, so tag deduplication and reindex snapshots are atomic.
write_lock = RLock()


def seed_tags(session):
    names = json.loads((ROOT / "data/tags.json").read_text(encoding="utf-8-sig"))
    synonyms = json.loads((ROOT / "data/synonyms.json").read_text(encoding="utf-8-sig"))
    existing = {t.normalized for t in session.scalars(select(Tag))}
    for name in names:
        if normalize(name) not in existing:
            session.add(Tag(name=name, normalized=normalize(name), synonyms=synonyms.get(name, [])))
    session.flush()


def tag_lookup(session):
    tags = list(session.scalars(select(Tag).order_by(Tag.id)))
    lookup = {t.normalized: t for t in tags}
    for tag in tags:
        for alias in tag.synonyms:
            lookup.setdefault(normalize(alias), tag)
    return lookup


def replace_synonyms(session, query):
    lookup = tag_lookup(session)
    if not lookup or not query:
        return query
    # Match the longest phrase first and replace only once: no replacement cascade.
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(s) for s in sorted(lookup, key=len, reverse=True)) + r")(?!\w)"
    return re.sub(pattern, lambda m: lookup[normalize(m.group())].name, query, flags=re.IGNORECASE)


def add_pending(session, name):
    key = normalize(name)
    if not session.scalar(select(FreeTag).where(FreeTag.normalized == key)):
        session.add(FreeTag(name=name.strip(), normalized=key))
        session.flush()


def make_solution(session, problem, data, code=None, origin="", existing=None):
    data = SolutionData.model_validate(data).model_dump()
    lookup = tag_lookup(session)
    closed = {}
    free = {}
    for name in data["tags"]:
        if tag := lookup.get(normalize(name)):
            closed[tag.id] = tag
        else:
            free.setdefault(normalize(name), name)
            add_pending(session, name)
    for name in data["free_tags"]:
        if normalize(name) not in lookup:
            free.setdefault(normalize(name), name)
            add_pending(session, name)
    # Historic free_tags must survive promotion to the closed vocabulary.
    historical = {normalize(n): n for n in data["free_tags"]}
    historical.update(free)
    data["tags"] = [t.name for t in closed.values()]
    data["free_tags"] = list(historical.values())
    solution = existing or Solution()
    solution.data, solution.code, solution.origin, solution.tags = data, code, origin, list(closed.values())
    if existing is None:
        problem.solutions.append(solution)
        session.add(solution)
    session.flush()
    return solution


def solution_json(solution, include_code=True):
    data = {**solution.data, "tags": [t.name for t in solution.tags]}
    if include_code:
        return {"id": solution.id, **data, "code": solution.code, "origin": solution.origin}
    return data


def problem_json(problem, detail=True):
    tags = sorted({t.name for s in problem.solutions for t in s.tags}, key=str.casefold)
    result = {
        "id": problem.id, "title": problem.title, "origin": problem.origin,
        "abstract": problem.statement_json.get("abstract", ""),
        "difficulty": problem.difficulty, "tags": tags,
        "solution_count": len(problem.solutions),
        "llm_solution_count": sum(s.data.get("source") == "llm" for s in problem.solutions),
        "created_at": problem.created_at.astimezone(timezone.utc).isoformat(), "updated_at": problem.updated_at.astimezone(timezone.utc).isoformat(),
    }
    if detail:
        result.update(statement=problem.original_statement, solutions=[solution_json(s) for s in problem.solutions],
                      analysis={"statement": problem.statement_json, "solutions": [solution_json(s, False) for s in problem.solutions]})
    return result


def refresh_search(session, problem):
    difficulties = [s.data.get("difficulty") for s in problem.solutions if s.data.get("difficulty") is not None]
    problem.difficulty = min(difficulties) if difficulties else None
    problem.updated_at = now()
    solutions = [solution_json(s, False) for s in problem.solutions]
    # Only closed tags may influence search. Code and difficulty_reason are not indexed.
    for data in solutions:
        data.pop("free_tags", None)
        data.pop("difficulty_reason", None)
    document = json.dumps({"statement": problem.statement_json, "solutions": solutions}, ensure_ascii=False, sort_keys=True)
    vector = embedder.embed(document)
    if problem.search_record:
        problem.search_record.document = document
        problem.search_record.embedding = vector
        problem.search_record.model = embedder.identity
    else:
        problem.search_record = SearchRecord(document=document, embedding=vector, model=embedder.identity)
    session.flush()


def get_problem(session, problem_id):
    problem = session.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "Задача не найдена")
    return problem


def get_solution(session, problem_id, solution_id):
    problem = get_problem(session, problem_id)
    solution = next((s for s in problem.solutions if s.id == solution_id), None)
    if not solution:
        raise HTTPException(404, "Решение не найдено")
    return problem, solution


def signature(data):
    return (tuple(sorted({normalize(t) for t in data.get("tags", [])})),
            data.get("complexity", {}).get("time", ""), data.get("complexity", {}).get("memory", ""))


def validate_analysis(analysis, inputs):
    if analysis.statement.image_required:
        raise HTTPException(422, "Для понимания задачи требуется изображение. Задача не сохранена.")
    if any(s.get("code") for s in inputs[len(analysis.solutions):]):
        raise HTTPException(502, "Не удалось сохранить соответствие решений и исходного кода")


def attach_analysis(session, problem, analysis, inputs):
    validate_analysis(analysis, inputs)
    for i, data in enumerate(analysis.solutions):
        source = inputs[i] if i < len(inputs) else {}
        payload = data.model_dump()
        if source.get("code"):
            payload.update(source="code", trusted=source.get("trusted", False))
        else:
            payload.update(source="llm", trusted=False)
        make_solution(session, problem, payload, source.get("code"), source.get("origin", ""))
