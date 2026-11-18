"""Persisted, observable jobs. Results commit atomically; failures leave data intact."""
import uuid
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import select

from .db import FreeTag, Job, Problem, Session, Tag
from .providers import analyzer, normalize
from .services import (attach_analysis, get_problem, make_solution, refresh_search,
                       signature, solution_json, tag_lookup, validate_analysis, write_lock)

job_lock = Lock()


def serialize_job(job):
    return {"id": job.id, "kind": job.kind, "status": job.status, "total": job.total,
            "completed": job.completed, "result": job.result, "error": job.error,
            "created_at": job.created_at.isoformat()}


def create_job(session, kind, problem_id=None):
    if session.scalar(select(Job).where(Job.status.in_(["pending", "running"]))):
        raise HTTPException(409, "Другая переиндексация уже выполняется")
    ids = list(session.scalars(select(Problem.id).order_by(Problem.id)))
    if problem_id is not None:
        get_problem(session, problem_id)
        ids = [problem_id]
    tags = [{"id": t.id, "name": t.name} for t in session.scalars(select(FreeTag).order_by(FreeTag.id))] if kind == "tags" else []
    if kind == "tags" and tags and analyzer_mode_is_demo():
        raise HTTPException(409, "Проверка применимости новых тегов требует настроенной LLM. Очередь сохранена.")
    job = Job(id=str(uuid.uuid4()), kind=kind, total=len(ids), snapshot={"problem_ids": ids, "tags": tags})
    session.add(job)
    session.flush()
    return job


def analyzer_mode_is_demo():
    from .config import settings
    return settings.llm_provider == "demo"


def run_job(job_id):
    with job_lock:
        try:
            with write_lock, Session.begin() as session:
                job = session.get(Job, job_id)
                job.status = "running"
                kind, snapshot = job.kind, job.snapshot
            # Generate outside write transactions, allowing new tasks and free tags.
            results = []
            for i, problem_id in enumerate(snapshot["problem_ids"]):
                with Session() as session:
                    problem = session.get(Problem, problem_id)
                    if not problem:
                        continue
                    inputs = [solution_json(s) for s in problem.solutions]
                    version = problem.updated_at.isoformat()
                    if kind == "tags":
                        lookup = tag_lookup(session)
                        candidates = [t["name"] for t in snapshot["tags"] if normalize(t["name"]) not in lookup]
                        analysis = analyzer.check_tags(problem.original_statement, inputs, candidates) if candidates else None
                    elif kind == "embeddings":
                        analysis = None
                    else:
                        analysis = analyzer.analyze(problem.title, problem.original_statement, inputs, [t.name for t in session.scalars(select(Tag))])
                        validate_analysis(analysis, inputs)
                    results.append((problem_id, version, inputs, analysis))
                with write_lock, Session.begin() as session:
                    session.get(Job, job_id).completed = i + 1
            with write_lock, Session.begin() as session:
                added = 0
                promoted = set()
                if kind == "tags":
                    accepted = {name for _, _, _, analysis in results if analysis for s in analysis.solutions for name in s.tags}
                    lookup = tag_lookup(session)
                    for name in sorted(accepted):
                        if normalize(name) not in lookup:
                            session.add(Tag(name=name, normalized=normalize(name), synonyms=[]))
                            promoted.add(name)
                    session.flush()
                for problem_id, version, inputs, analysis in results:
                    problem = session.get(Problem, problem_id)
                    if problem is None or problem.updated_at.isoformat() != version:
                        raise HTTPException(409, "Во время анализа задача изменилась. Результаты отменены; повторите запуск.")
                    if kind == "problem":
                        # Delete old rows before adding new ones, while keeping source code in inputs.
                        problem.solutions.clear()
                        session.flush()
                        problem.statement_json = analysis.statement.model_dump()
                        attach_analysis(session, problem, analysis, inputs)
                        added += len(analysis.solutions)
                    elif kind == "bank":
                        seen = {signature(solution_json(s, False)) for s in problem.solutions}
                        for index, data in enumerate(analysis.solutions):
                            # Normalize unknown/alias tags before signature comparison.
                            lookup = tag_lookup(session)
                            payload = data.model_dump()
                            payload["free_tags"] = list(dict.fromkeys(payload["free_tags"] + [t for t in payload["tags"] if normalize(t) not in lookup]))
                            payload["tags"] = list({lookup[normalize(t)].name for t in payload["tags"] if normalize(t) in lookup})
                            if signature(payload) not in seen:
                                src = inputs[index] if index < len(inputs) else {}
                                payload.update(source="code" if src.get("code") else "llm", trusted=src.get("trusted", False) if src.get("code") else False)
                                new = make_solution(session, problem, payload, src.get("code"), src.get("origin", ""))
                                seen.add(signature(solution_json(new, False)))
                                added += 1
                    elif kind == "tags" and analysis:
                        for data in analysis.solutions:
                            make_solution(session, problem, data.model_dump())
                            added += 1
                    refresh_search(session, problem)
                if kind == "tags":
                    # Delete only the exact pending rows captured at start.
                    for item in snapshot["tags"]:
                        row = session.get(FreeTag, item["id"])
                        if row and row.name == item["name"]:
                            session.delete(row)
                job = session.get(Job, job_id)
                job.status, job.completed = "succeeded", job.total
                job.result = {"solutions_added": added, "promoted_tags": sorted(promoted)}
        except Exception as exc:
            with write_lock, Session.begin() as session:
                job = session.get(Job, job_id)
                job.status = "failed"
                job.error = str(exc.detail) if isinstance(exc, HTTPException) else "Ошибка обработки. Изменения отменены; подробности в журнале сервера."
            if not isinstance(exc, HTTPException):
                import logging
                logging.getLogger(__name__).exception("Reindex job failed: %s", job_id)
