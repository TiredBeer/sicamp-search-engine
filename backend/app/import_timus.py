"""Import a Timus folder through the running API; no direct database access."""
import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import httpx
from pydantic import ValidationError

from .schemas import InternalProblemInput, SolutionInput


CODE_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c", ".py", ".java", ".pas", ".cs", ".kt", ".rs", ".go", ".js"}


@dataclass(frozen=True)
class Entry:
    number: str
    statement: Path
    solutions: tuple[Path, ...]


def discover(folder: Path) -> list[Entry]:
    entries = {}
    code_by_folder = {}
    for statement in folder.rglob("*_statement.txt"):
        if not statement.is_file():
            continue
        match = re.fullmatch(r"(\d+)_statement\.txt", statement.name)
        if not match:
            continue
        number = str(int(match[1]))
        if number in entries:
            raise ValueError(f"Повторяющийся номер Timus {number}: {entries[number].statement} и {statement}")
        if statement.parent not in code_by_folder:
            code_by_folder[statement.parent] = [p for p in statement.parent.iterdir()
                                               if p.suffix.lower() in CODE_EXTENSIONS and p.is_file()]
        pattern = re.compile(rf"{re.escape(match[1])}(?:[_.-].+)?")
        solutions = tuple(sorted((p for p in code_by_folder[statement.parent]
                                  if pattern.fullmatch(p.stem)), key=lambda p: p.name.casefold()))
        entries[number] = Entry(number, statement, solutions)
    return sorted(entries.values(), key=lambda entry: int(entry.number))


def read_source(path: Path, encoding: str) -> str:
    data = path.read_bytes()
    if encoding != "auto":
        return data.decode(encoding)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251")


def make_payload(entry: Entry, encoding: str, trusted: bool) -> InternalProblemInput:
    statement = read_source(entry.statement, encoding)
    first_line = next((line.strip() for line in statement.splitlines() if line.strip()), "")
    title = re.sub(rf"^{re.escape(entry.number)}[.)]\s*", "", first_line)
    if not title:
        raise ValueError("Пустое условие")
    solutions = []
    for path in entry.solutions:
        code = read_source(path, encoding)
        if not code.strip():
            raise ValueError(f"Пустой файл решения: {path.name}")
        solutions.append(SolutionInput(code=code, source="code", trusted=trusted,
                                       origin=f"Timus {entry.number}: {path.name}"))
    return InternalProblemInput(title=f"Timus {entry.number}. {title}", statement=statement,
                                origin=f"https://acm.timus.ru/problem.aspx?num={entry.number}",
                                solutions=solutions)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Значение должно быть больше нуля")
    return number


def save_report(path, folder, results):
    if path is None:
        return
    body = {"folder": str(folder), "updated_at": datetime.now(timezone.utc).isoformat(),
            "counts": dict(Counter(item["status"] for item in results)), "items": results}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def error_detail(response):
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    # Validation responses may echo input code. Do not dump those into reports.
    return detail if isinstance(detail, str) else f"HTTP {response.status_code}: ответ API не принят"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Импорт Timus: <номер>_statement.txt и соседние файлы кода.")
    parser.add_argument("folder", type=Path, help="Путь к timus-master (обход вложенных папок)")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Адрес работающего backend")
    parser.add_argument("--ids", nargs="+", type=positive_int, help="Только указанные номера Timus")
    parser.add_argument("--limit", type=positive_int, help="Максимум выбранных задач за запуск, включая уже импортированные")
    parser.add_argument("--dry-run", action="store_true", help="Проверить файлы без API, LLM и записи в БД")
    parser.add_argument("--encoding", choices=["auto", "utf-8-sig", "cp1251"], default="auto")
    parser.add_argument("--trusted-solutions", action="store_true", help="Пометить исходные решения как доверенные AC-решения")
    parser.add_argument("--timeout", type=positive_int, default=600, help="Ожидание ответа API в секундах")
    parser.add_argument("--report", type=Path, help="Сохранять JSON-отчёт после каждой задачи")
    args = parser.parse_args(argv)
    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        parser.error(f"Папка не найдена: {folder}")
    try:
        entries = discover(folder)
        if not entries:
            raise ValueError("Файлы <номер>_statement.txt не найдены")
        found = len(entries)
        if args.ids:
            missing = set(map(str, args.ids)) - {entry.number for entry in entries}
            if missing:
                raise ValueError("Не найдены задачи: " + ", ".join(sorted(missing, key=int)))
            entries = [entry for entry in entries if int(entry.number) in args.ids]
        if args.limit:
            entries = entries[:args.limit]
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Найдено: {found}; выбрано: {len(entries)}; файлов решений: {sum(len(e.solutions) for e in entries)}", flush=True)
    results = []
    try:
        save_report(args.report, folder, results)
    except OSError as exc:
        parser.error(f"Не удалось создать отчёт: {exc}")
    with httpx.Client(base_url=args.api_url.rstrip("/") + "/", timeout=args.timeout) as client:
        if not args.dry_run:
            try:
                response = client.get("api/health")
                response.raise_for_status()
                health = response.json()
                if health.get("llm_provider") != "gateway" or not health.get("llm_configured"):
                    parser.error("Backend должен использовать настроенную реальную LLM (LLM_PROVIDER=gateway/auto и ключ)")
            except (httpx.HTTPError, ValueError) as exc:
                print(f"Backend недоступен: {type(exc).__name__}", file=sys.stderr)
                return 2
        try:
            for index, entry in enumerate(entries, 1):
                item = {"number": entry.number, "statement": str(entry.statement),
                        "solution_files": [str(path) for path in entry.solutions]}
                try:
                    payload = make_payload(entry, args.encoding, args.trusted_solutions)
                    print(f"[{index}/{len(entries)}] {payload.title}: файлов решений {len(payload.solutions)}", flush=True)
                    if args.dry_run:
                        item["status"] = "ready"
                    else:
                        response = client.post("api/internal/problems", json=payload.model_dump(),
                                               headers={"Import-Key": f"timus:{entry.number}"})
                        if response.status_code not in (200, 201):
                            raise ValueError(error_detail(response))
                        problem = response.json()
                        item.update(status="imported" if response.status_code == 201 else "skipped",
                                    problem_id=problem["id"],
                                    solutions=[{"id": s["id"], "source": s["source"],
                                                "difficulty": s["difficulty"], "complexity": s["complexity"]}
                                               for s in problem["solutions"]])
                        print(f"  {item['status']}: ID {item['problem_id']}, решений {len(problem['solutions'])}", flush=True)
                except ValidationError as exc:
                    item.update(status="failed", error="; ".join(
                        f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                        for error in exc.errors(include_input=False)))
                except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                    item.update(status="failed", error=str(exc))
                except httpx.HTTPError as exc:
                    item.update(status="failed", error=f"Сетевая ошибка {type(exc).__name__}. Повторите команду для продолжения.")
                results.append(item)
                if item["status"] == "failed":
                    print(f"  Ошибка: {item['error']}", file=sys.stderr, flush=True)
                try:
                    save_report(args.report, folder, results)
                except OSError as exc:
                    print(f"Не удалось записать отчёт: {exc}. Сохранённые задачи останутся в БД.", file=sys.stderr)
                    return 2
        except KeyboardInterrupt:
            print("\nИмпорт остановлен. Повторите команду: сохранённые задачи будут пропущены.", file=sys.stderr)
            return 130
    counts = Counter(item["status"] for item in results)
    print("Итог: " + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())), flush=True)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    # Windows pipes otherwise inherit a legacy codepage and can fail on titles
    # containing mathematical symbols or characters outside Cyrillic/Latin.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(main())
