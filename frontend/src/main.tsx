import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Code2,
  FileJson,
  Filter,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Tags,
  Trash2,
  X,
} from "lucide-react";
import type {
  Health,
  Job,
  ProblemDetail,
  SearchResults,
  Solution,
  Stats,
  Tag,
} from "./types";
import { api } from "./api";
import "./styles.css";

const emptySolution = (): Solution => ({
  source: "code",
  trusted: false,
  key_idea: "",
  sketch: "",
  facts: [],
  reduction: [],
  tags: [],
  free_tags: [],
  difficulty: null,
  difficulty_reason: "",
  complexity: { time: "", memory: "" },
  prerequisite: [],
  code: "",
  origin: "",
});
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Произошла ошибка";
const jobNames: Record<string, string> = {
  bank: "Анализ банка задач",
  problem: "Анализ задачи",
  tags: "Переиндексация тегов",
  embeddings: "Перестроение эмбеддингов",
};
const statusNames: Record<string, string> = {
  pending: "В очереди",
  running: "Выполняется",
  succeeded: "Завершено",
  failed: "Ошибка",
};

function Modal({
  title,
  subtitle,
  children,
  close,
  wide = false,
  page = false,
  busy = false,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  close: () => void;
  wide?: boolean;
  page?: boolean;
  busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    el.showModal();
    const cancel = (event: Event) => {
      event.preventDefault();
      closeRef.current();
    };
    el.addEventListener("cancel", cancel);
    return () => {
      el.removeEventListener("cancel", cancel);
      el.close();
    };
  }, []);
  if (page)
    return (
      <div className="editor-page">
        <div className="editor-container">
          <button className="back-link" onClick={close}>
            <ArrowLeft size={16} />
            {title === "Добавить задачу" ? "Все задачи" : "К задаче"}
            <span>/</span>
            {title.startsWith("Редактировать")
              ? "Редактирование"
              : title.includes("решени")
                ? "Новое решение"
                : "Новая задача"}
          </button>
          <div className="editor-layout">
            <div>
              <div className="modal-head">
                <h1>{title}</h1>
                <div className="actions">
                  <button
                    className="btn secondary"
                    onClick={close}
                    disabled={busy}
                  >
                    Отмена
                  </button>
                  <button
                    className="btn primary"
                    type="submit"
                    disabled={busy}
                    form={
                      title.includes("решени")
                        ? "solution-editor"
                        : "problem-editor"
                    }
                  >
                    Сохранить {title.includes("решени") ? "решение" : "задачу"}
                  </button>
                </div>
              </div>
              {children}
            </div>
            <aside className="editor-aside">
              <h3>
                {title.includes("решени")
                  ? "Если решение сгенерировано"
                  : "Обязательные поля"}
              </h3>
              <p>
                {title.includes("решени")
                  ? "Отметьте «Сгенерировано LLM»."
                  : "Название, условие."}
              </p>
              <h3>
                {title.includes("решени")
                  ? "Если нужный тег не нашёлся"
                  : "Решения необязательны"}
              </h3>
              <p>
                {title.includes("решени")
                  ? "Добавьте новый свободный тег. Он попадёт в очередь переиндексации."
                  : "Можно сохранить задачу и добавить решение позже."}
              </p>
            </aside>
          </div>
        </div>
      </div>
    );
  return (
    <dialog ref={dialog} className={wide ? "modal wide" : "modal"}>
      <div className="modal-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <button className="icon-btn" aria-label="Закрыть" onClick={close}>
          <X size={21} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

function ErrorBox({ error }: { error: string }) {
  return error ? (
    <div className="error-box" role="alert">
      {error}
    </div>
  ) : null;
}
function Badge({ value }: { value: number | null }) {
  return (
    <span
      className={`difficulty ${value == null ? "none" : value <= 3 ? "easy" : value <= 6 ? "medium" : "hard"}`}
    >
      <span />
      {value == null ? "Не задана" : `${value} из 10`}
    </span>
  );
}
function Chips({ names, free = false }: { names: string[]; free?: boolean }) {
  return (
    <>
      {names.map((name) => (
        <span className={`tag ${free ? "free" : ""}`} key={name}>
          {free && <Plus size={11} />} {name}
        </span>
      ))}
    </>
  );
}

function TagSelector({
  tags,
  selected,
  onChange,
}: {
  tags: Tag[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  return (
    <div className="tag-selector">
      <div className="mini-search">
        <Search size={15} />
        <input
          aria-label="Найти тег"
          placeholder="Найти тег или синоним"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="tag-options">
        {tags
          .filter((t) =>
            [t.name, ...t.synonyms].some((x) =>
              x.toLowerCase().includes(query.toLowerCase()),
            ),
          )
          .map((tag) => (
            <label key={tag.id}>
              <input
                type="checkbox"
                checked={selected.includes(tag.name)}
                onChange={() =>
                  onChange(
                    selected.includes(tag.name)
                      ? selected.filter((x) => x !== tag.name)
                      : [...selected, tag.name],
                  )
                }
              />
              <span>{tag.name}</span>
            </label>
          ))}
      </div>
    </div>
  );
}

function SolutionFields({
  value,
  change,
  tags,
}: {
  value: Solution;
  change: (v: Solution) => void;
  tags: Tag[];
}) {
  return (
    <div className="form-fields">
      <label>
        Название или ключевая идея
        <input
          value={value.key_idea}
          onChange={(e) => change({ ...value, key_idea: e.target.value })}
          placeholder="Введите название или ключевую идею"
          maxLength={2000}
        />
      </label>
      <div className="form-row">
        <label>
          Время <b>*</b>
          <input
            required
            value={value.complexity.time}
            onChange={(e) =>
              change({
                ...value,
                complexity: { ...value.complexity, time: e.target.value },
              })
            }
            placeholder="O(n log n)"
            maxLength={200}
          />
        </label>
        <label>
          Память <b>*</b>
          <input
            required
            value={value.complexity.memory}
            onChange={(e) =>
              change({
                ...value,
                complexity: { ...value.complexity, memory: e.target.value },
              })
            }
            placeholder="O(n)"
            maxLength={200}
          />
        </label>
        <label>
          Сложность <b>*</b>
          <select
            required
            value={value.difficulty ?? ""}
            onChange={(e) =>
              change({
                ...value,
                difficulty:
                  e.target.value === "" ? null : Number(e.target.value),
              })
            }
          >
            <option value="">Выберите сложность (1–10)</option>
            {Array.from({ length: 10 }, (_, i) => (
              <option key={i} value={i + 1}>
                {i + 1} из 10
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Описание алгоритма
        <textarea
          rows={3}
          value={value.sketch}
          onChange={(e) => change({ ...value, sketch: e.target.value })}
        />
      </label>
      <div>
        <span className="field-label">Теги решения</span>
        <div className="selected-tags">
          <Chips names={value.tags} />
        </div>
        <TagSelector
          tags={tags}
          selected={value.tags}
          onChange={(t) => change({ ...value, tags: t })}
        />
      </div>
      <label>
        Свободные теги <span className="muted">через запятую</span>
        <input
          value={value.free_tags.join(", ")}
          onChange={(e) =>
            change({
              ...value,
              free_tags: e.target.value.split(",").map((x) => x.trimStart()),
            })
          }
          onBlur={() =>
            change({
              ...value,
              free_tags: value.free_tags.map((x) => x.trim()).filter(Boolean),
            })
          }
          placeholder="Новая техника"
        />
      </label>
      <label>
        Исходный код
        <textarea
          className="code-input"
          rows={5}
          value={value.code ?? ""}
          onChange={(e) => change({ ...value, code: e.target.value })}
          placeholder="// Код необязателен"
          maxLength={500000}
        />
      </label>
      <label>
        Источник
        <input
          value={value.origin}
          onChange={(e) => change({ ...value, origin: e.target.value })}
          placeholder="Ссылка или название"
          maxLength={1000}
        />
      </label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={value.source === "llm"}
          onChange={(e) =>
            change({
              ...value,
              source: e.target.checked ? "llm" : "code",
              trusted: false,
            })
          }
        />
        Сгенерировано LLM
      </label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={value.trusted}
          onChange={(e) => change({ ...value, trusted: e.target.checked })}
        />
        Решение проверено
      </label>
    </div>
  );
}

function ProblemForm({
  problem,
  tags,
  health,
  close,
  saved,
}: {
  problem?: ProblemDetail;
  tags: Tag[];
  health?: Health;
  close: () => void;
  saved: (p: ProblemDetail) => void;
}) {
  const [value, setValue] = useState({
    title: problem?.title ?? "",
    statement: problem?.statement ?? "",
    abstract: problem?.abstract ?? "",
    origin: problem?.origin ?? "",
  });
  const [solutions, setSolutions] = useState<Solution[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const payload = problem
        ? value
        : {
            ...value,
            abstract: value.abstract || null,
            solutions: solutions.map((s) => ({
              ...s,
              free_tags: s.free_tags.map((x) => x.trim()).filter(Boolean),
            })),
          };
      saved(
        await api<ProblemDetail>(
          problem ? `/problems/${problem.id}` : "/problems",
          problem ? "PUT" : "POST",
          payload,
        ),
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={problem ? "Редактировать задачу" : "Добавить задачу"}
      subtitle={
        problem
          ? "Изменения сохранятся без повторного анализа LLM"
          : "Добавьте условие — и задача появится в банке"
      }
      close={() => !busy && close()}
      busy={busy}
      wide
      page
    >
      <form id="problem-editor" onSubmit={submit}>
        <div className="modal-content form-fields">
          <ErrorBox error={error} />
          {!problem && health?.llm_provider === "demo" && (
            <div className="notice">
              Деморежим: условие и ваши решения сохранятся без вызова LLM. Новые
              подходы автоматически не генерируются.
            </div>
          )}
          <label>
            Название <b>*</b>
            <input
              autoFocus
              required
              value={value.title}
              onChange={(e) => setValue({ ...value, title: e.target.value })}
              maxLength={300}
              placeholder="Например, кратчайший путь"
            />
          </label>
          <label>
            Условие задачи <b>*</b>
            <textarea
              required
              rows={8}
              value={value.statement}
              onChange={(e) =>
                setValue({ ...value, statement: e.target.value })
              }
              placeholder="Полный текст с ограничениями, форматом ввода и вывода"
              maxLength={500000}
            />
          </label>
          <label>
            Математическая постановка
            <textarea
              rows={3}
              value={value.abstract}
              onChange={(e) => setValue({ ...value, abstract: e.target.value })}
              placeholder="Условие без легенды — необязательно"
            />
          </label>
          <label>
            Источник
            <input
              value={value.origin}
              onChange={(e) => setValue({ ...value, origin: e.target.value })}
              placeholder="Timus, Codeforces или ссылка"
              maxLength={1000}
            />
          </label>
          {!problem && (
            <div className="initial-solutions">
              <h3>
                Известные решения <span>{solutions.length}</span>
              </h3>
              {solutions.map((s, i) => (
                <details key={i} open>
                  <summary>
                    Решение {i + 1}
                    <button
                      type="button"
                      className="icon-btn danger"
                      aria-label={`Убрать решение ${i + 1}`}
                      onClick={(e) => {
                        e.preventDefault();
                        setSolutions(solutions.filter((_, n) => n !== i));
                      }}
                    >
                      <X size={16} />
                    </button>
                  </summary>
                  <SolutionFields
                    value={s}
                    tags={tags}
                    change={(v) =>
                      setSolutions(solutions.map((x, n) => (n === i ? v : x)))
                    }
                  />
                </details>
              ))}
              <button
                type="button"
                className="btn secondary"
                onClick={() => setSolutions([...solutions, emptySolution()])}
              >
                <Plus size={16} />
                Добавить решение
              </button>
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button
            type="button"
            className="btn secondary"
            onClick={close}
            disabled={busy}
          >
            Отмена
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Check size={16} />
            )}{" "}
            {busy ? "Сохраняем…" : "Сохранить задачу"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function SolutionForm({
  problemId,
  solution,
  tags,
  close,
  saved,
}: {
  problemId: number;
  solution?: Solution;
  tags: Tag[];
  close: () => void;
  saved: (p: ProblemDetail) => void;
}) {
  const [value, change] = useState(solution ?? emptySolution()),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError("");
    setBusy(true);
    try {
      saved(
        await api<ProblemDetail>(
          `/problems/${problemId}/solutions${solution ? "/" + solution.id : ""}`,
          solution ? "PUT" : "POST",
          {
            ...value,
            free_tags: value.free_tags.map((x) => x.trim()).filter(Boolean),
          },
        ),
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={solution ? "Редактировать решение" : "Добавить решение"}
      subtitle="Теги и сложность обновят поисковые данные задачи"
      close={() => !busy && close()}
      busy={busy}
      page
    >
      <form id="solution-editor" onSubmit={submit}>
        <div className="modal-content">
          <ErrorBox error={error} />
          <SolutionFields value={value} tags={tags} change={change} />
        </div>
        <div className="modal-footer">
          <button
            type="button"
            className="btn secondary"
            onClick={close}
            disabled={busy}
          >
            Отмена
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Check size={16} />
            )}{" "}
            Сохранить решение
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AddTag({
  problemId,
  solution,
  tags,
  close,
  saved,
}: {
  problemId: number;
  solution: Solution;
  tags: Tag[];
  close: () => void;
  saved: (p: ProblemDetail) => void;
}) {
  const [kind, setKind] = useState("closed"),
    [name, setName] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      saved(
        await api(
          `/problems/${problemId}/solutions/${solution.id}/tags`,
          "POST",
          { kind, name },
        ),
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Добавить тег к решению"
      close={() => !busy && close()}
      busy={busy}
    >
      <form onSubmit={submit}>
        <div className="modal-content form-fields">
          <ErrorBox error={error} />
          <div className="segmented">
            <button
              type="button"
              className={kind === "closed" ? "active" : ""}
              onClick={() => {
                setKind("closed");
                setName("");
              }}
            >
              Из списка
            </button>
            <button
              type="button"
              className={kind === "free" ? "active" : ""}
              onClick={() => {
                setKind("free");
                setName("");
              }}
            >
              Новый тег
            </button>
          </div>
          {kind === "closed" ? (
            <label>
              Закрытый тег
              <select
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              >
                <option value="">Выберите тег</option>
                {tags.map((t) => (
                  <option key={t.id} value={t.name}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <>
              <label>
                Название
                <input
                  autoFocus
                  required
                  maxLength={120}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Название новой техники"
                />
              </label>
              <div className="notice">
                Свободный тег сразу появится у решения. Для включения в поиск
                потребуется переиндексация тегов.
              </div>
            </>
          )}
        </div>
        <div className="modal-footer">
          <button
            type="button"
            className="btn secondary"
            onClick={close}
            disabled={busy}
          >
            Отмена
          </button>
          <button className="btn primary" disabled={busy}>
            {busy && <LoaderCircle size={16} className="spin" />}Добавить
          </button>
        </div>
      </form>
    </Modal>
  );
}

function App() {
  const [page, setPage] = useState<"bank" | "tags" | "manage">("bank");
  const [tags, setTags] = useState<Tag[]>([]),
    [health, setHealth] = useState<Health>(),
    [stats, setStats] = useState<Stats>({
      problems: 0,
      solutions: 0,
      tags: 0,
      pending_tags: 0,
    });
  const [query, setQuery] = useState(""),
    [submitted, setSubmitted] = useState(""),
    [selectedTags, setSelectedTags] = useState<string[]>([]),
    [difficulty, setDifficulty] = useState(""),
    [sort, setSort] = useState("relevance"),
    [offset, setOffset] = useState(0);
  const [results, setResults] = useState<SearchResults>({
      items: [],
      total: 0,
      query: "",
    }),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [mobileFilters, setMobileFilters] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(() => {
      const id = new URLSearchParams(location.search).get("problem");
      return id && /^\d+$/.test(id) ? Number(id) : null;
    }),
    [detail, setDetail] = useState<ProblemDetail>(),
    [detailLoading, setDetailLoading] = useState(false);
  const [problemForm, setProblemForm] = useState<"new" | "edit" | null>(null),
    [solutionForm, setSolutionForm] = useState<Solution | "new" | null>(null),
    [tagSolution, setTagSolution] = useState<Solution | null>(null),
    [viewSolution, setViewSolution] = useState<Solution | null>(null);
  const [confirm, setConfirm] = useState<{
      title: string;
      text: string;
      action: () => Promise<void>;
      label: string;
      destructive?: boolean;
    } | null>(null),
    [confirmBusy, setConfirmBusy] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]),
    [pendingTags, setPendingTags] = useState<{ id: number; name: string }[]>(
      [],
    ),
    [tagQuery, setTagQuery] = useState(""),
    [revision, setRevision] = useState(0),
    [toast, setToast] = useState("");
  const previousJobs = useRef<Record<string, string>>({}),
    activeJob = jobs.find((j) => ["pending", "running"].includes(j.status));
  const refresh = () => setRevision((x) => x + 1);
  const selectProblem = (id: number | null) => {
    setError("");
    setSelectedId(id);
    const u = new URL(location.href);
    id
      ? u.searchParams.set("problem", String(id))
      : u.searchParams.delete("problem");
    history.replaceState(null, "", u);
    window.scrollTo({ top: 0 });
  };
  const navigate = (next: typeof page) => {
    setPage(next);
    selectProblem(null);
    setProblemForm(null);
    setSolutionForm(null);
  };
  const count = (n: number) =>
    n === 0
      ? "Нет решений"
      : `${n} ${n % 10 === 1 && n % 100 !== 11 ? "решение" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "решения" : "решений"}`;
  const date = (v: string) =>
    new Date(v).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  useEffect(() => {
    const c = new AbortController();
    Promise.all([
      api<Tag[]>("/tags", "GET", undefined, c.signal),
      api<Stats>("/stats", "GET", undefined, c.signal),
      api<Health>("/health", "GET", undefined, c.signal),
      api<{ id: number; name: string }[]>(
        "/tags/pending",
        "GET",
        undefined,
        c.signal,
      ),
    ])
      .then(([t, s, h, p]) => {
        setTags(t);
        setStats(s);
        setHealth(h);
        setPendingTags(p);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(message(e));
      });
    return () => c.abort();
  }, [revision]);
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    const p = new URLSearchParams({
      q: submitted,
      offset: String(offset),
      limit: "5",
      sort,
    });
    selectedTags.forEach((t) => p.append("tags", t));
    if (difficulty) p.set("difficulty", difficulty);
    api<SearchResults>("/problems?" + p, "GET", undefined, c.signal)
      .then(setResults)
      .catch((e) => {
        if (e.name !== "AbortError") setError(message(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [submitted, selectedTags, difficulty, sort, offset, revision]);
  useEffect(() => {
    if (selectedId === null) {
      setDetail(undefined);
      return;
    }
    const c = new AbortController();
    setDetail(undefined);
    setDetailLoading(true);
    api<ProblemDetail>(`/problems/${selectedId}`, "GET", undefined, c.signal)
      .then(setDetail)
      .catch((e) => {
        if (e.name !== "AbortError") setError(message(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setDetailLoading(false);
      });
    return () => c.abort();
  }, [selectedId, revision]);
  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const next = await api<Job[]>("/jobs");
        if (!live) return;
        for (const j of next) {
          const prev = previousJobs.current[j.id];
          if (
            prev &&
            prev !== j.status &&
            ["succeeded", "failed"].includes(j.status)
          ) {
            refresh();
            setToast(
              j.status === "succeeded"
                ? `${jobNames[j.kind]}: завершено`
                : j.error || "Ошибка переиндексации",
            );
          }
        }
        previousJobs.current = Object.fromEntries(
          next.map((j) => [j.id, j.status]),
        );
        setJobs(next);
      } catch {
        /* Connection errors appear in main requests. */
      }
    };
    void poll();
    const timer = setInterval(poll, 2500);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!loading && offset > 0 && results.total <= offset) setOffset(0);
  }, [loading, offset, results.total]);
  const saved = (p: ProblemDetail) => {
    setProblemForm(null);
    setSolutionForm(null);
    setTagSolution(null);
    setDetail(p);
    selectProblem(p.id);
    setPage("bank");
    refresh();
    setToast("Изменения сохранены");
  };
  const reset = () => {
    setSelectedTags([]);
    setDifficulty("");
    setOffset(0);
  };
  const schedule = async (kind: string) => {
    const job = await api<Job>(
      kind === "problem"
        ? `/problems/${selectedId}/reindex`
        : `/reindex/${kind}`,
      "POST",
    );
    previousJobs.current[job.id] = job.status;
    setJobs((prev) => [job, ...prev]);
    setToast("Переиндексация запущена");
  };
  const reindex = (kind: string) =>
    setConfirm({
      title: jobNames[kind],
      text:
        kind === "problem"
          ? "Все решения заменятся результатами нового анализа. Исходный код сохранится по порядку решений."
          : kind === "bank"
            ? "Все задачи будут проанализированы повторно. Существующие решения сохранятся; добавятся только новые."
            : kind === "tags"
              ? "LLM проверит свободные теги на всех задачах. Применимые теги войдут в закрытый список. При успехе обработанная очередь будет очищена."
              : "Эмбеддинги всех задач будут пересчитаны текущей моделью. Вызовы внешней модели могут расходовать квоту.",
      label: "Запустить",
      action: () => schedule(kind),
    });
  const removeSolution = (s: Solution) =>
    setConfirm({
      title: "Удалить решение?",
      text: "Задача и другие её решения сохранятся.",
      label: "Удалить",
      destructive: true,
      action: async () => {
        await api(`/problems/${selectedId}/solutions/${s.id}`, "DELETE");
        refresh();
        setToast("Решение удалено");
      },
    });
  const totalPages = Math.ceil(results.total / 5),
    currentPage = offset / 5 + 1;
  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <a
            href="/"
            className="brand"
            onClick={(e) => {
              e.preventDefault();
              navigate("bank");
            }}
          >
            LKL
            <span />
          </a>
          <nav aria-label="Основная навигация">
            <button
              className={page === "bank" ? "active" : ""}
              onClick={() => navigate("bank")}
            >
              Поиск задач
            </button>
            <button
              className={page === "tags" ? "active" : ""}
              onClick={() => navigate("tags")}
            >
              Управление тегами
            </button>
            <button
              className={page === "manage" ? "active" : ""}
              onClick={() => navigate("manage")}
            >
              Банк задач
            </button>
          </nav>
          <span className="header-caption">Алгоритмы. Идеи. Практика.</span>
        </div>
      </header>
      <main>
        <ErrorBox error={error} />
        {activeJob && (
          <div className="job-banner">
            <LoaderCircle className="spin" size={16} />
            {jobNames[activeJob.kind]}
            <span>
              {activeJob.completed} / {activeJob.total}
            </span>
          </div>
        )}
        {page === "bank" && selectedId === null && (
          <>
            <div className="page-heading">
              <h1>Поиск задач</h1>
              <button
                className="btn primary"
                onClick={() => setProblemForm("new")}
              >
                <Plus size={17} />
                Добавить задачу
              </button>
            </div>
            <section className="search-area">
              <form
                className="search-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  setError("");
                  setSubmitted(query);
                  setOffset(0);
                }}
              >
                <Search size={21} />
                <input
                  aria-label="Поисковый запрос"
                  placeholder="Опишите задачу, алгоритм или идею"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                {query && (
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label="Очистить запрос"
                    onClick={() => {
                      setQuery("");
                      setSubmitted("");
                      setOffset(0);
                    }}
                  >
                    <X size={17} />
                  </button>
                )}
                <button type="submit" className="btn primary">
                  Найти
                </button>
              </form>
              {!!selectedTags.length && (
                <div className="active-filters">
                  {selectedTags.map((t) => (
                    <button
                      key={t}
                      onClick={() => {
                        setSelectedTags(selectedTags.filter((x) => x !== t));
                        setOffset(0);
                      }}
                    >
                      {t}
                      <X size={12} />
                    </button>
                  ))}
                </div>
              )}
              {health?.embedding_provider === "local" && (
                <p className="mode-caption">
                  Деморежим: локальное текстовое ранжирование. Семантический
                  поиск доступен после подключения модели эмбеддингов.
                </p>
              )}
            </section>
            <div className="search-layout">
              <aside
                className={`filters ${mobileFilters ? "mobile-open" : ""}`}
              >
                <h2>
                  <Filter size={17} />
                  Фильтры
                </h2>
                <h3>Теги</h3>
                <TagSelector
                  tags={tags}
                  selected={selectedTags}
                  onChange={(t) => {
                    setSelectedTags(t);
                    setOffset(0);
                  }}
                />
                <p className="filter-note">Хотя бы один из выбранных тегов</p>
                <div className="filter-divider" />
                <label className="field-label">
                  Сложность
                  <select
                    aria-label="Сложность задачи"
                    value={difficulty}
                    onChange={(e) => {
                      setDifficulty(e.target.value);
                      setOffset(0);
                    }}
                  >
                    <option value="">Сложность: любая</option>
                    {Array.from({ length: 10 }, (_, i) => (
                      <option key={i} value={i + 1}>
                        {i + 1} из 10
                      </option>
                    ))}
                  </select>
                </label>
                <button className="reset-filters" onClick={reset}>
                  Сбросить
                </button>
              </aside>
              <section className="results">
                <div className="results-heading">
                  <h2>
                    {loading
                      ? "Ищем задачи…"
                      : `Найдено ${results.total} задач`}
                  </h2>
                  <div className="actions">
                    <button
                      className="btn secondary mobile-filter"
                      onClick={() => setMobileFilters((v) => !v)}
                    >
                      <Filter size={15} />
                      Фильтры
                    </button>
                    <select
                      aria-label="Порядок результатов"
                      className="sort-select"
                      value={sort}
                      onChange={(e) => {
                        setSort(e.target.value);
                        setOffset(0);
                      }}
                    >
                      <option value="relevance">По релевантности</option>
                      <option value="newest">Сначала новые</option>
                      <option value="oldest">Сначала старые</option>
                    </select>
                  </div>
                </div>
                {results.query && results.query !== submitted && (
                  <p className="normalized">
                    С учётом синонимов: {results.query}
                  </p>
                )}
                {loading ? (
                  <div className="loading">
                    <LoaderCircle className="spin" size={28} />
                  </div>
                ) : results.items.length ? (
                  <div className="result-list">
                    {results.items.map((p) => (
                      <article className="result-card" key={p.id}>
                        <div className="result-title">
                          <button onClick={() => selectProblem(p.id)}>
                            <h3>{p.title}</h3>
                          </button>
                          <Badge value={p.difficulty} />
                        </div>
                        <p className="result-abstract">
                          {p.abstract ||
                            "Математическая постановка пока не добавлена."}
                        </p>
                        <div className="tag-line">
                          <Chips names={p.tags} />
                        </div>
                        <div className="result-footer">
                          <span>
                            {count(p.solution_count)}
                            {p.origin && ` · ${p.origin}`}
                          </span>
                          <button
                            className="open-link"
                            onClick={() => selectProblem(p.id)}
                          >
                            Открыть
                            <ArrowRight size={15} />
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="empty">
                    <Search size={29} />
                    <h3>Задач не найдено</h3>
                    <p>Измените запрос или сбросьте фильтры.</p>
                    <button
                      className="btn secondary"
                      onClick={() => {
                        reset();
                        setQuery("");
                        setSubmitted("");
                      }}
                    >
                      Сбросить поиск
                    </button>
                  </div>
                )}
                {results.total > 0 && (
                  <div className="pagination">
                    <span>
                      {offset + 1}–{Math.min(offset + 5, results.total)} из{" "}
                      {results.total}
                    </span>
                    <div>
                      <button
                        className="page-arrow"
                        aria-label="Предыдущая страница"
                        disabled={offset === 0}
                        onClick={() => setOffset(offset - 5)}
                      >
                        <ArrowLeft size={16} />
                      </button>
                      {Array.from({ length: totalPages }, (_, i) => i + 1)
                        .filter(
                          (n) =>
                            n === 1 ||
                            n === totalPages ||
                            Math.abs(n - currentPage) <= 1,
                        )
                        .map((n, i, arr) => (
                          <React.Fragment key={n}>
                            {i > 0 && n - arr[i - 1] > 1 && (
                              <span className="ellipsis">…</span>
                            )}
                            <button
                              className={
                                n === currentPage
                                  ? "page-number active"
                                  : "page-number"
                              }
                              aria-label={`Страница ${n}`}
                              aria-current={
                                n === currentPage ? "page" : undefined
                              }
                              onClick={() => setOffset((n - 1) * 5)}
                            >
                              {n}
                            </button>
                          </React.Fragment>
                        ))}
                      <button
                        className="page-arrow"
                        aria-label="Следующая страница"
                        disabled={offset + 5 >= results.total}
                        onClick={() => setOffset(offset + 5)}
                      >
                        <ArrowRight size={16} />
                      </button>
                    </div>
                  </div>
                )}
                <button
                  className="bank-reindex text-button"
                  disabled={!!activeJob}
                  onClick={() => reindex("bank")}
                >
                  <RefreshCw size={15} />
                  Переиндексировать банк задач
                </button>
              </section>
            </div>
          </>
        )}
        {page === "bank" && selectedId !== null && (
          <>
            <button className="back-link" onClick={() => selectProblem(null)}>
              <ArrowLeft size={16} />
              Все задачи
            </button>
            {detailLoading ? (
              <div className="loading">
                <LoaderCircle className="spin" size={28} />
              </div>
            ) : (
              detail && (
                <>
                  <div className="page-heading detail-heading">
                    <h1>{detail.title}</h1>
                    <div className="actions">
                      <button
                        className="btn secondary"
                        onClick={() => setProblemForm("edit")}
                      >
                        <Pencil size={15} />
                        Редактировать
                      </button>
                      <button
                        className="btn danger-secondary"
                        onClick={() =>
                          setConfirm({
                            title: "Удалить задачу?",
                            text: "Условие, решения, исходный код и поисковые данные будут удалены.",
                            label: "Удалить",
                            destructive: true,
                            action: async () => {
                              await api(`/problems/${detail.id}`, "DELETE");
                              selectProblem(null);
                              refresh();
                              setToast("Задача удалена");
                            },
                          })
                        }
                      >
                        <Trash2 size={15} />
                        Удалить
                      </button>
                    </div>
                  </div>
                  <div className="detail-summary">
                    <div className="tag-line">
                      <Chips names={detail.tags} />
                    </div>
                    <div>
                      <Badge value={detail.difficulty} />
                      <span>
                        {count(detail.solutions.length)} · Обновлено{" "}
                        {date(detail.updated_at)}
                      </span>
                    </div>
                  </div>
                  <div className="detail-layout">
                    <div>
                      <section className="white-panel statement-panel">
                        <h2>Условие</h2>
                        <p className="pre-wrap">{detail.statement}</p>
                        {detail.abstract && (
                          <>
                            <div className="section-divider" />
                            <h2>Математическая постановка</h2>
                            <p className="pre-wrap">{detail.abstract}</p>
                          </>
                        )}
                      </section>
                      <section className="solutions-section">
                        <div className="section-heading">
                          <h2>Решения · {detail.solutions.length}</h2>
                          <button
                            className="text-button"
                            onClick={() => setSolutionForm("new")}
                          >
                            <Plus size={16} />
                            Добавить решение
                          </button>
                        </div>
                        {detail.solutions.map((s, i) => (
                          <article className="solution-card" key={s.id}>
                            <h3>{s.key_idea || `Решение ${i + 1}`}</h3>
                            <div className="solution-meta">
                              Время {s.complexity.time || "—"} · Память{" "}
                              {s.complexity.memory || "—"}
                              {s.source === "llm" && (
                                <span className="llm-label">
                                  <Sparkles size={13} />
                                  Сгенерировано LLM
                                </span>
                              )}
                              {s.trusted && (
                                <span className="trusted">
                                  <Check size={13} />
                                  Проверено
                                </span>
                              )}
                            </div>
                            <div className="solution-tag-row">
                              <span>Теги:</span>
                              <div className="tag-line">
                                <Chips names={s.tags} />
                                <Chips names={s.free_tags} free />
                                <button
                                  className="tag add-tag"
                                  onClick={() => setTagSolution(s)}
                                >
                                  <Plus size={12} />
                                  Добавить тег
                                </button>
                              </div>
                            </div>
                            <div className="solution-difficulty">
                              Сложность: <Badge value={s.difficulty} />
                            </div>
                            <div className="solution-actions">
                              <button onClick={() => setViewSolution(s)}>
                                Посмотреть
                              </button>
                              <button onClick={() => setSolutionForm(s)}>
                                Редактировать
                              </button>
                              <button
                                className="danger"
                                onClick={() => removeSolution(s)}
                              >
                                Удалить
                              </button>
                            </div>
                          </article>
                        ))}
                        {!detail.solutions.length && (
                          <div className="empty compact">
                            <Code2 size={26} />
                            <h3>Нет решений</h3>
                            <p>
                              Добавьте решение вручную или запустите
                              переиндексацию.
                            </p>
                          </div>
                        )}
                      </section>
                      <button
                        className="btn secondary reindex-problem"
                        disabled={!!activeJob}
                        onClick={() => reindex("problem")}
                      >
                        <RefreshCw size={15} />
                        Переиндексировать задачу
                      </button>
                      <details className="analysis-json">
                        <summary>
                          <FileJson size={15} />
                          JSON задачи
                        </summary>
                        <pre>{JSON.stringify(detail.analysis, null, 2)}</pre>
                      </details>
                    </div>
                    <aside className="detail-aside">
                      <h3>Источник задачи</h3>
                      <p>{detail.origin || "Не указан"}</p>
                      <div className="aside-divider" />
                      <h3>О решениях</h3>
                      <p>
                        Каждый подход имеет свои теги, сложность и асимптотику.
                      </p>
                      <p className="muted">
                        Отметка LLM показывает происхождение решения.
                      </p>
                    </aside>
                  </div>
                </>
              )
            )}
          </>
        )}
        {page === "tags" && (
          <>
            <div className="page-heading">
              <h1>Управление тегами</h1>
              <button
                className="btn secondary"
                disabled={!!activeJob}
                onClick={() => reindex("tags")}
              >
                <RefreshCw size={16} />
                Переиндексировать теги
              </button>
            </div>
            <div className="white-panel pending-panel">
              <h2>Новые теги · {pendingTags.length}</h2>
              <p className="muted">
                Ожидают проверки применимости; пока не участвуют в поиске.
              </p>
              <div className="tag-line">
                {pendingTags.length ? (
                  <Chips names={pendingTags.map((t) => t.name)} free />
                ) : (
                  <span className="muted">Нет необработанных тегов</span>
                )}
              </div>
            </div>
            <div className="dictionary white-panel">
              <div className="section-heading">
                <h2>Закрытый список · {tags.length}</h2>
              </div>
              <div className="mini-search dictionary-search">
                <Search size={17} />
                <input
                  aria-label="Поиск в словаре"
                  placeholder="Найти тег или синоним"
                  value={tagQuery}
                  onChange={(e) => setTagQuery(e.target.value)}
                />
              </div>
              <p className="muted">
                Синонимы фиксированы. Новые теги добавляются к решениям и входят
                в закрытый список после переиндексации.
              </p>
              {tags
                .filter((t) =>
                  [t.name, ...t.synonyms].some((n) =>
                    n.toLowerCase().includes(tagQuery.toLowerCase()),
                  ),
                )
                .map((t) => (
                  <div className="dictionary-row" key={t.id}>
                    <strong>
                      <Tags size={14} />
                      {t.name}
                    </strong>
                    <span>{t.synonyms.join(" · ") || "Нет синонимов"}</span>
                  </div>
                ))}
            </div>
          </>
        )}
        {page === "manage" && (
          <>
            <div className="page-heading">
              <h1>Банк задач</h1>
              <button
                className="btn primary"
                onClick={() => {
                  setPage("bank");
                  setProblemForm("new");
                }}
              >
                <Plus size={17} />
                Добавить задачу
              </button>
            </div>
            <div className="bank-summary">
              <span>{stats.problems} задач</span>
              <span>{stats.solutions} решений</span>
              <span>{stats.tags} тегов</span>
              <span>PostgreSQL + pgvector</span>
            </div>
            <div className="notice mode-notice">
              {health?.llm_provider === "demo"
                ? "Деморежим: автоматический анализ LLM отключён."
                : "Анализ задач выполняется через LLM Gateway."}{" "}
              {health?.embedding_provider === "local"
                ? "Поиск использует локальное текстовое ранжирование."
                : "Для поиска подключена внешняя модель эмбеддингов."}
            </div>
            <div className="management-grid">
              {[
                {
                  kind: "bank",
                  title: "Переиндексировать банк задач",
                  text: "Повторно проанализировать все задачи. Сохранить существующие решения и добавить новые.",
                },
                {
                  kind: "tags",
                  title: "Переиндексировать теги",
                  text: "Проверить свободные теги, добавить подходящие решения и расширить закрытый список.",
                },
                {
                  kind: "embeddings",
                  title: "Обновить поисковый индекс",
                  text: "Пересчитать эмбеддинги текущей моделью, без повторного анализа условий.",
                },
              ].map((item) => (
                <article className="white-panel" key={item.kind}>
                  <RefreshCw size={22} />
                  <h2>{item.title}</h2>
                  <p>{item.text}</p>
                  <button
                    className="btn secondary"
                    disabled={!!activeJob}
                    onClick={() => reindex(item.kind)}
                  >
                    Запустить
                  </button>
                </article>
              ))}
            </div>
            <div className="section-heading">
              <h2>История заданий</h2>
              <button
                className="text-button"
                onClick={async () => {
                  try {
                    setJobs(await api("/jobs"));
                    refresh();
                  } catch (e) {
                    setError(message(e));
                  }
                }}
              >
                <RefreshCw size={14} />
                Обновить
              </button>
            </div>
            <div className="white-panel jobs-panel">
              {jobs.length ? (
                jobs.map((j) => (
                  <div className="job-row" key={j.id}>
                    <span className={`job-status ${j.status}`}>
                      {j.status === "running" ? (
                        <LoaderCircle className="spin" size={18} />
                      ) : j.status === "succeeded" ? (
                        <Check size={18} />
                      ) : j.status === "failed" ? (
                        <X size={18} />
                      ) : (
                        <RefreshCw size={17} />
                      )}
                    </span>
                    <div>
                      <h3>{jobNames[j.kind]}</h3>
                      <p>
                        {j.error ||
                          `${j.completed} из ${j.total} задач · ${date(j.created_at)}`}
                      </p>
                      {j.result.solutions_added !== undefined && (
                        <span>
                          Новых решений: {j.result.solutions_added} · Новых
                          тегов: {j.result.promoted_tags?.length ?? 0}
                        </span>
                      )}
                    </div>
                    <span>{statusNames[j.status]}</span>
                  </div>
                ))
              ) : (
                <div className="empty compact">
                  <p>Переиндексаций пока не было</p>
                </div>
              )}
            </div>
          </>
        )}
      </main>
      <footer>
        <span>LKL</span>
        <p>Находите задачи. Пробуйте подходы.</p>
      </footer>
      {problemForm && (
        <ProblemForm
          problem={problemForm === "edit" ? detail : undefined}
          tags={tags}
          health={health}
          close={() => setProblemForm(null)}
          saved={saved}
        />
      )}
      {solutionForm && detail && (
        <SolutionForm
          problemId={detail.id}
          solution={solutionForm === "new" ? undefined : solutionForm}
          tags={tags}
          close={() => setSolutionForm(null)}
          saved={saved}
        />
      )}
      {tagSolution && detail && (
        <AddTag
          problemId={detail.id}
          solution={tagSolution}
          tags={tags}
          close={() => setTagSolution(null)}
          saved={saved}
        />
      )}
      {viewSolution && (
        <Modal
          title={viewSolution.key_idea || "Решение"}
          close={() => setViewSolution(null)}
          wide
        >
          <div className="modal-content solution-view">
            <div className="solution-meta">
              Время {viewSolution.complexity.time || "—"} · Память{" "}
              {viewSolution.complexity.memory || "—"}
              {viewSolution.source === "llm" && (
                <span className="llm-label">
                  <Sparkles size={13} />
                  Сгенерировано LLM
                </span>
              )}
            </div>
            <div className="tag-line">
              <Chips names={viewSolution.tags} />
              <Chips names={viewSolution.free_tags} free />
            </div>
            <p>
              Сложность: <Badge value={viewSolution.difficulty} />
            </p>
            {viewSolution.sketch && (
              <p className="pre-wrap">{viewSolution.sketch}</p>
            )}
            {viewSolution.difficulty_reason && (
              <p className="muted">{viewSolution.difficulty_reason}</p>
            )}
            {viewSolution.facts.map((f, i) => (
              <p key={i}>
                {f.name && <strong>{f.name}: </strong>}
                {f.statement}
              </p>
            ))}
            {!!viewSolution.reduction.length && (
              <ol>
                {viewSolution.reduction.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ol>
            )}
            {!!viewSolution.prerequisite.length && (
              <p>Нужно знать: {viewSolution.prerequisite.join(", ")}</p>
            )}
            <h3>Код</h3>
            {viewSolution.code ? (
              <pre className="source-code">{viewSolution.code}</pre>
            ) : (
              <p className="muted">Исходный код не добавлен</p>
            )}
            {viewSolution.origin && (
              <p className="muted">Источник: {viewSolution.origin}</p>
            )}
          </div>
        </Modal>
      )}
      {confirm && (
        <Modal
          title={confirm.title}
          close={() => !confirmBusy && setConfirm(null)}
        >
          <div className="modal-content">
            <p>{confirm.text}</p>
          </div>
          <div className="modal-footer">
            <button
              className="btn secondary"
              disabled={confirmBusy}
              onClick={() => setConfirm(null)}
            >
              Отмена
            </button>
            <button
              className={`btn ${confirm.destructive ? "destructive" : "primary"}`}
              disabled={confirmBusy}
              onClick={async () => {
                setConfirmBusy(true);
                try {
                  await confirm.action();
                  setConfirm(null);
                } catch (e) {
                  setToast(message(e));
                  setConfirm(null);
                } finally {
                  setConfirmBusy(false);
                }
              }}
            >
              {confirmBusy && <LoaderCircle className="spin" size={15} />}{" "}
              {confirm.label}
            </button>
          </div>
        </Modal>
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
          <button
            className="icon-btn"
            aria-label="Скрыть уведомление"
            onClick={() => setToast("")}
          >
            <X size={17} />
          </button>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
