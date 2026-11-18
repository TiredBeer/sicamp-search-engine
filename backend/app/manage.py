"""Maintenance commands. No LLM calls and no changes to tasks or solutions."""
import argparse

from sqlalchemy import delete, select, text

from .config import settings
from .db import Job, Problem, SearchRecord, Session, init_db
from .services import refresh_search


def rebuild_search():
    init_db()
    with Session.begin() as session:
        if session.scalar(select(Job).where(Job.status.in_(["pending", "running"]))):
            raise RuntimeError("Дождитесь завершения активной переиндексации")
        # All changes, including DDL and vectors, commit together or roll back.
        session.execute(delete(SearchRecord))
        session.execute(text("DROP INDEX IF EXISTS ix_search_embedding"))
        dimensions = settings.embedding_dimensions
        session.execute(text(f"ALTER TABLE search_records ALTER COLUMN embedding TYPE vector({dimensions})"))
        problems = list(session.scalars(select(Problem).order_by(Problem.id)))
        for problem in problems:
            refresh_search(session, problem)
        session.execute(text("CREATE INDEX ix_search_embedding ON search_records USING hnsw (embedding vector_cosine_ops)"))
    print(f"Перестроен поиск для {len(problems)} задач. Размерность: {dimensions}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Обслуживание LKL")
    parser.add_argument("command", choices=["rebuild-search"])
    parser.parse_args()
    rebuild_search()
