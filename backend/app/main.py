from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text, update

from .config import settings
from .db import FreeTag, Job, Problem, SearchRecord, Session, Solution, Tag, init_db
from .jobs import create_job, run_job, serialize_job
from .providers import analyzer, embedder, normalize, query_enricher, reranker
from .schemas import InternalProblemInput, ManualSolution, ProblemEdit, ProblemInput, TagInput
from .seed import seed_demo
from .services import (attach_analysis, get_problem, get_solution, make_solution, problem_json,
                       refresh_search, replace_synonyms, seed_tags, solution_json, tag_lookup,
                       validate_analysis, write_lock)


@asynccontextmanager
async def lifespan(app):
    init_db()
    with write_lock, Session.begin() as session:
        seed_tags(session)
        session.execute(update(Job).where(Job.status.in_(["pending", "running"])).values(status="failed", error="Сервер перезапущен. Запустите переиндексацию повторно."))
        if settings.seed_demo and session.scalar(select(func.count()).select_from(Problem)) == 0:
            seed_demo(session)
    yield


app = FastAPI(title="LKL · Поиск задач", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    with Session() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok", "llm_provider": settings.llm_provider, "embedding_provider": settings.embedding_provider,
            "embedding_model": embedder.identity, "llm_configured": bool(settings.llm_api_key)}


@app.get("/api/stats")
def stats():
    with Session() as session:
        return {name: session.scalar(select(func.count()).select_from(model)) for name, model in
                [("problems", Problem), ("solutions", Solution), ("tags", Tag), ("pending_tags", FreeTag)]}


@app.get("/api/tags")
def tags():
    with Session() as session:
        return [{"id": t.id, "name": t.name, "synonyms": t.synonyms} for t in session.scalars(select(Tag).order_by(Tag.name))]


@app.get("/api/tags/pending")
def pending_tags():
    with Session() as session:
        return [{"id": t.id, "name": t.name} for t in session.scalars(select(FreeTag).order_by(FreeTag.id))]


@app.get("/api/problems")
def search(q: str = Query(default="", max_length=4000), tags: list[str] = Query(default=[]),
           sort: Literal["relevance", "newest", "oldest"] = "relevance",
           difficulty: int | None = Query(default=None, ge=1, le=10),
           difficulty_min: int = Query(default=1, ge=1, le=10),
           difficulty_max: int = Query(default=10, ge=1, le=10),
           offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
    if difficulty_min > difficulty_max:
        raise HTTPException(422, "Минимальная сложность больше максимальной")
    with Session() as session:
        query = select(Problem)
        if tags:
            lookup = tag_lookup(session)
            ids = {lookup[normalize(t)].id for t in tags if normalize(t) in lookup}
            if not ids:
                return {"items": [], "total": 0, "query": q, "offset": offset, "limit": limit}
            query = query.where(Problem.solutions.any(Solution.tags.any(Tag.id.in_(ids))))
        if difficulty is not None:
            query = query.where(Problem.difficulty == difficulty)
        elif difficulty_min != 1 or difficulty_max != 10:
            query = query.where(Problem.difficulty.between(difficulty_min, difficulty_max))
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        processed = query_enricher.process(replace_synonyms(session, q.strip()))
        scores = {}
        if processed:
            mismatch = session.scalar(select(func.count()).select_from(SearchRecord).where(SearchRecord.model != embedder.identity))
            if mismatch:
                raise HTTPException(409, "Модель эмбеддингов изменилась. Перестройте поисковый индекс.")
            vector = embedder.embed(processed)
            # Exact cosine ranking after filtering avoids HNSW post-filter recall loss.
            session.execute(text("SET LOCAL enable_indexscan = off"))
            distance = SearchRecord.embedding.cosine_distance(vector)
            ordering = (distance, Problem.id) if sort == "relevance" else (Problem.id.desc() if sort == "newest" else Problem.id.asc(),)
            rows = session.execute(query.join(SearchRecord).add_columns(distance.label("distance")).order_by(*ordering).offset(offset).limit(limit)).all()
            problems = [row[0] for row in rows]
            scores = {row[0].id: 1 - float(row[1]) for row in rows}
        else:
            problems = list(session.scalars(query.order_by(Problem.id.asc() if sort == "oldest" else Problem.id.desc()).offset(offset).limit(limit)))
        items = [{**problem_json(p, False), "score": scores.get(p.id)} for p in problems]
        return {"items": reranker.process(items), "total": total, "query": processed, "offset": offset, "limit": limit}


def add_problem(payload):
    inputs = [s.model_dump() for s in payload.solutions]
    with Session() as session:
        closed = [t.name for t in session.scalars(select(Tag))]
    analysis = analyzer.analyze(payload.title, payload.statement, inputs, closed)
    validate_analysis(analysis, inputs)
    if payload.abstract is not None:
        analysis.statement.abstract = payload.abstract
    with write_lock, Session.begin() as session:
        problem = Problem(title=payload.title, original_statement=payload.statement, origin=payload.origin, statement_json=analysis.statement.model_dump())
        session.add(problem)
        session.flush()
        attach_analysis(session, problem, analysis, inputs)
        refresh_search(session, problem)
        return problem_json(problem)


@app.post("/api/problems", status_code=201)
def create_problem(payload: ProblemInput):
    return add_problem(payload)


@app.post("/api/internal/problems", status_code=201)
def internal_create_problem(payload: InternalProblemInput):
    return add_problem(payload)


@app.get("/api/problems/{problem_id}")
def read_problem(problem_id: int):
    with Session() as session:
        return problem_json(get_problem(session, problem_id))


@app.put("/api/problems/{problem_id}")
def edit_problem(problem_id: int, payload: ProblemEdit):
    with write_lock, Session.begin() as session:
        problem = get_problem(session, problem_id)
        problem.title, problem.original_statement, problem.origin = payload.title, payload.statement, payload.origin
        problem.statement_json = {**problem.statement_json, "abstract": payload.abstract}
        refresh_search(session, problem)
        return problem_json(problem)


@app.delete("/api/problems/{problem_id}", status_code=204)
def delete_problem(problem_id: int):
    with write_lock, Session.begin() as session:
        session.delete(get_problem(session, problem_id))


@app.post("/api/problems/{problem_id}/solutions", status_code=201)
def create_solution(problem_id: int, payload: ManualSolution):
    with write_lock, Session.begin() as session:
        problem = get_problem(session, problem_id)
        validate_manual_free_tags(session, payload.free_tags)
        make_solution(session, problem, payload.model_dump(), payload.code, payload.origin)
        refresh_search(session, problem)
        return problem_json(problem)


@app.put("/api/problems/{problem_id}/solutions/{solution_id}")
def edit_solution(problem_id: int, solution_id: int, payload: ManualSolution):
    with write_lock, Session.begin() as session:
        problem, solution = get_solution(session, problem_id, solution_id)
        validate_manual_free_tags(session, payload.free_tags, solution.data.get("free_tags", []))
        make_solution(session, problem, payload.model_dump(), payload.code, payload.origin, existing=solution)
        refresh_search(session, problem)
        return problem_json(problem)


def validate_manual_free_tags(session, names, historic=()):
    lookup = tag_lookup(session)
    historical = {normalize(t) for t in historic}
    for name in names:
        if normalize(name) in historical:
            continue
        if tag := lookup.get(normalize(name)):
            raise HTTPException(409, f'Тег уже существует. Выберите «{tag.name}» из закрытого списка.')


@app.delete("/api/problems/{problem_id}/solutions/{solution_id}", status_code=204)
def delete_solution(problem_id: int, solution_id: int):
    with write_lock, Session.begin() as session:
        problem, solution = get_solution(session, problem_id, solution_id)
        problem.solutions.remove(solution)
        session.flush()
        refresh_search(session, problem)


@app.post("/api/problems/{problem_id}/solutions/{solution_id}/tags")
def add_solution_tag(problem_id: int, solution_id: int, payload: TagInput):
    with write_lock, Session.begin() as session:
        problem, solution = get_solution(session, problem_id, solution_id)
        tag = tag_lookup(session).get(normalize(payload.name))
        if payload.kind == "free" and tag:
            raise HTTPException(409, f'Тег уже существует. Выберите «{tag.name}» из закрытого списка.')
        if payload.kind == "closed" and not tag:
            raise HTTPException(404, "Тег отсутствует в закрытом списке")
        data = solution_json(solution, False)
        key = "tags" if payload.kind == "closed" else "free_tags"
        name = tag.name if tag else payload.name
        if normalize(name) not in {normalize(t) for t in data[key]}:
            data[key] = [*data[key], name]
        make_solution(session, problem, data, solution.code, solution.origin, existing=solution)
        refresh_search(session, problem)
        return problem_json(problem)


def schedule_job(background_tasks, kind, problem_id=None):
    with write_lock, Session.begin() as session:
        job = create_job(session, kind, problem_id)
        result = serialize_job(job)
    background_tasks.add_task(run_job, job.id)
    return result


@app.post("/api/reindex/bank", status_code=202)
def reindex_bank(background_tasks: BackgroundTasks):
    return schedule_job(background_tasks, "bank")


@app.post("/api/reindex/tags", status_code=202)
def reindex_tags(background_tasks: BackgroundTasks):
    return schedule_job(background_tasks, "tags")


@app.post("/api/reindex/embeddings", status_code=202)
def reindex_embeddings(background_tasks: BackgroundTasks):
    return schedule_job(background_tasks, "embeddings")


@app.post("/api/problems/{problem_id}/reindex", status_code=202)
def reindex_problem(problem_id: int, background_tasks: BackgroundTasks):
    return schedule_job(background_tasks, "problem", problem_id)


@app.get("/api/jobs")
def jobs():
    with Session() as session:
        return [serialize_job(j) for j in session.scalars(select(Job).order_by(Job.created_at.desc()).limit(30))]


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str):
    with Session() as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Задание не найдено")
        return serialize_job(job)
