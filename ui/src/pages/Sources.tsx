import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  Check,
  Download,
  Library,
  Plus,
  Search,
  UploadCloud,
  X,
} from "lucide-react";
import { api, invalidate, responseError, useAll, useAPI, write } from "../api";
import { canWrite, useAuth } from "../auth";
import type { Job, RawFile } from "../types";
import {
  Badge,
  Empty,
  ErrorBanner,
  Heading,
  Loading,
  Modal,
  Submit,
  bytes,
  useAction,
  useToast,
} from "../components/common";

interface Source extends RawFile {
  processed: boolean;
}
interface Chapter {
  n: number;
  title: string;
  page_from: number;
  page_to: number;
}
export default function Sources() {
  const { actor } = useAuth(),
    allowed = actor?.clearance === "restricted",
    files = useAll<Source>("/raw", allowed),
    [query, setQuery] = useState(""),
    [upload, setUpload] = useState(false),
    [params, setParams] = useSearchParams();
  const selected = params.get("path"),
    rows = (files.data || []).filter((f) =>
      (f.original_name || f.path).toLowerCase().includes(query.toLowerCase()),
    );
  if (!allowed)
    return (
      <Empty
        icon={Library}
        title="Для источников нужен ограниченный допуск"
        text="Ваш токен позволяет читать доступные страницы вики. Исходные документы доступны участникам с допуском restricted."
      />
    );
  return (
    <div className="page-enter">
      <Heading
        eyebrow="ИЗ ИСТОЧНИКОВ — В ЗНАНИЯ"
        title="Библиотека команды"
        description="Книги, документы и материалы, на которых основаны ваши решения."
      >
        {canWrite(actor) && (
          <button className="button primary" onClick={() => setUpload(true)}>
            <Plus size={17} />
            Добавить источник
          </button>
        )}
      </Heading>
      <div className="library-intro">
        <div className="book-stack" aria-hidden="true">
          <span />
          <span />
          <span />
          <BookOpen size={31} />
        </div>
        <div>
          <h2>Пусть хорошие книги работают на вас.</h2>
          <p>
            Загрузите источник. Агент извлечёт идеи, свяжет их с вики
            <br />и предложит кандидатов на новые правила.
          </p>
        </div>
        <Link className="text-link" to="/jobs">
          Посмотреть задачи <ArrowUpRight size={15} />
        </Link>
      </div>
      <div className="catalog-toolbar">
        <div className="filter-search">
          <Search size={17} />
          <input
            placeholder="Найти документ…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск источников"
          />
        </div>
        <span className="muted">{files.data?.length || 0} материалов</span>
      </div>
      <ErrorBanner error={files.error} />
      {files.isPending ? (
        <Loading lines={5} />
      ) : rows.length ? (
        <div className="source-grid">
          {rows.map((file, i) => (
            <button
              className="source-card"
              key={file.path}
              onClick={() => setParams({ path: file.path })}
            >
              <div className={`source-cover cover-${i % 4}`}>
                <span>{file.path.split(".").pop()?.toUpperCase()}</span>
                <BookOpen size={38} />
                <div className="cover-lines">
                  <i />
                  <i />
                  <i />
                </div>
              </div>
              <div className="source-card-content">
                <Badge value={file.processed ? "verified" : "pending"} />
                <h3>{file.original_name || file.path.split("/").pop()}</h3>
                <p>
                  {file.path.startsWith("library/") ? "Библиотека" : "Документ"}{" "}
                  · {bytes(file.size || file.bytes)}
                </p>
                <span className="source-card-action">
                  Открыть источник <ArrowUpRight size={16} />
                </span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <Empty
          icon={UploadCloud}
          title={
            query ? "Такого документа пока нет" : "Первая полка пока пуста"
          }
          text="Добавьте книгу или документ — из него может начаться новое правило."
        >
          {canWrite(actor) && (
            <button className="button primary" onClick={() => setUpload(true)}>
              Загрузить источник
            </button>
          )}
        </Empty>
      )}
      {upload && (
        <Upload
          onClose={() => setUpload(false)}
          done={(path) => {
            setUpload(false);
            setParams({ path });
          }}
        />
      )}
      {selected && (
        <SourceDetails
          key={selected}
          path={selected}
          file={files.data?.find((f) => f.path === selected)}
          onClose={() => setParams({})}
        />
      )}
    </div>
  );
}
function Upload({
  onClose,
  done,
}: {
  onClose: () => void;
  done: (path: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null),
    [category, setCategory] = useState("library"),
    [note, setNote] = useState(""),
    [drag, setDrag] = useState(false),
    action = useAction(),
    ref = useRef<HTMLInputElement>(null);
  const send = () =>
    action.run(async () => {
      const data = new FormData();
      data.set("file", file!);
      data.set("category", category);
      data.set("note", note);
      const result = await api<RawFile>("/raw", { method: "POST", body: data });
      await invalidate();
      done(result.path);
    });
  return (
    <Modal
      title="Добавить источник"
      onClose={() => {
        if (!action.busy) onClose();
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <button
          type="button"
          className={`upload-zone ${drag ? "dragging" : ""}`}
          onClick={() => ref.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            setFile(e.dataTransfer.files[0] || null);
          }}
        >
          <UploadCloud size={33} />
          <strong>{file ? file.name : "Перетащите файл сюда"}</strong>
          <span>{file ? bytes(file.size) : "или нажмите, чтобы выбрать"}</span>
          <small>PDF, EPUB, DOCX, Markdown, TXT</small>
        </button>
        <input
          hidden
          ref={ref}
          type="file"
          accept=".pdf,.epub,.docx,.md,.txt,.csv,.json,.yaml,.yml"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <label className="field">
          Раздел
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="library">
              Библиотека — книги и объёмные материалы
            </option>
            <option value="docs">Документы</option>
            <option value="transcripts">Расшифровки встреч</option>
            <option value="api-specs">Спецификации</option>
            <option value="code-samples">Примеры кода</option>
          </select>
        </label>
        <label className="field">
          Заметка <span className="field-note">необязательно</span>
          <textarea
            rows={2}
            placeholder="Откуда документ и чем он полезен команде"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <ErrorBanner error={action.error} />
        <div className="modal-footer">
          <span className="muted">Исходник сохранится без изменений.</span>
          <Submit busy={action.busy} disabled={!file}>
            {action.busy ? "Загружаем файл…" : "Добавить в библиотеку"}
          </Submit>
        </div>
      </form>
    </Modal>
  );
}
function SourceDetails({
  path,
  file,
  onClose,
}: {
  path: string;
  file?: Source;
  onClose: () => void;
}) {
  const { actor } = useAuth(),
    [title, setTitle] = useState(
      file?.original_name?.replace(/\.[^.]+$/, "") || "",
    ),
    [author, setAuthor] = useState(""),
    [job, setJob] = useState(""),
    [edit, setEdit] = useState(false),
    [chapters, setChapters] = useState<Chapter[]>([]),
    [text, setText] = useState(""),
    [chapter, setChapter] = useState(""),
    [next, setNext] = useState<{ pages?: string; offset?: number }>({}),
    action = useAction(),
    toast = useToast();
  const outline = useAPI<{ chapters: Chapter[]; origin: string }>(
      `/raw/${path}/outline`,
    ),
    raw = `/raw/${path}`;
  const extract = () =>
    action.run(async () => {
      const result = await write<{ status: string }>(raw + "/extract");
      toast(
        result.status === "done"
          ? "Текст готов"
          : "Извлечение запущено. Обновите оглавление через несколько секунд.",
      );
      await outline.refetch();
    });
  const ingest = () =>
    action.run(async () => {
      const result = await write<Job>(
        "/jobs/ingest-book",
        {
          raw_path: path,
          ...(title ? { title } : {}),
          ...(author ? { author } : {}),
        },
        "POST",
        true,
      );
      setJob(result.id);
      await invalidate();
    });
  const read = () =>
    action.run(async () => {
      const result = await api<{
        text: string;
        next_pages?: string;
        next_offset?: number;
      }>(
        raw +
          "/text?max_chars=20000" +
          (next.pages
            ? `&pages=${encodeURIComponent(next.pages)}&offset=${next.offset || 0}`
            : outline.data?.chapters.length
              ? `&chapter=${chapter || outline.data.chapters[0].n}`
              : ""),
      );
      setText((old) => (next.pages ? old + "\n" + result.text : result.text));
      setNext({ pages: result.next_pages, offset: result.next_offset });
    });
  const download = () =>
    action.run(async () => {
      const response = await fetch("/api/v1" + raw, {
        credentials: "same-origin",
        redirect: "manual",
      });
      if (!response.ok) await responseError(response);
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = file?.original_name || path.split("/").pop() || "source";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  return (
    <Modal
      title={file?.original_name || path.split("/").pop() || "Источник"}
      onClose={onClose}
      wide
    >
      <div className="source-detail-toolbar">
        <Badge value={path.startsWith("library/") ? "book" : "source"} />
        <button className="button small" onClick={() => void download()}>
          <Download size={14} />
          Скачать оригинал
        </button>
        {canWrite(actor) && (
          <Submit
            busy={action.busy}
            className="button small"
            onClick={() => void extract()}
          >
            Извлечь текст
          </Submit>
        )}
      </div>
      <p className="muted path-label">{path}</p>
      {!!outline.data?.chapters.length && (
        <label className="field">
          Глава для чтения
          <select
            value={chapter || String(outline.data.chapters[0].n)}
            onChange={(e) => {
              setChapter(e.target.value);
              setText("");
              setNext({});
            }}
          >
            {outline.data.chapters.map((c) => (
              <option key={c.n} value={c.n}>
                {c.n}. {c.title}
              </option>
            ))}
          </select>
        </label>
      )}
      <ErrorBanner error={action.error} />
      {job ? (
        <div className="success-callout">
          <Check size={20} />
          <div>
            <strong>Агент начал разбор</strong>
            <p>Прогресс, кандидаты и результаты появятся в задаче.</p>
          </div>
          <Link
            className="button primary small"
            to={`/jobs?selected=${job}`}
            onClick={onClose}
          >
            Открыть задачу <ArrowUpRight size={14} />
          </Link>
        </div>
      ) : (
        canWrite(actor) && (
          <div className="ingest-form">
            <h3>Превратить источник в знания</h3>
            <div className="editor-meta">
              <label className="field">
                Название
                <input
                  value={title}
                  minLength={3}
                  maxLength={120}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </label>
              <label className="field">
                Автор
                <input
                  value={author}
                  maxLength={200}
                  onChange={(e) => setAuthor(e.target.value)}
                />
              </label>
            </div>
            <Submit busy={action.busy} onClick={() => void ingest()}>
              Разобрать с агентом <ArrowUpRight size={15} />
            </Submit>
          </div>
        )
      )}
      <div className="section-title">
        <h3>Оглавление</h3>
        <div className="inline-actions">
          <button className="text-link" onClick={() => void outline.refetch()}>
            Обновить
          </button>
          {canWrite(actor) && outline.data && (
            <button
              className="text-link"
              onClick={() => {
                setChapters(outline.data!.chapters);
                setEdit(true);
              }}
            >
              Уточнить
            </button>
          )}
        </div>
      </div>
      {outline.isPending ? (
        <Loading />
      ) : outline.data ? (
        <>
          {outline.data.origin === "fallback" && (
            <p className="callout">
              Главы определены по диапазонам страниц. Уточните оглавление, чтобы
              агент мог продолжить разбор.
            </p>
          )}
          {edit ? (
            <div className="outline-editor">
              {chapters.map((c, i) => (
                <div key={i}>
                  <input
                    aria-label={`Название главы ${i + 1}`}
                    value={c.title}
                    onChange={(e) =>
                      setChapters(
                        chapters.map((v, n) =>
                          n === i ? { ...v, title: e.target.value } : v,
                        ),
                      )
                    }
                  />
                  <input
                    aria-label={`Начало главы ${i + 1}`}
                    type="number"
                    min="1"
                    value={c.page_from}
                    onChange={(e) =>
                      setChapters(
                        chapters.map((v, n) =>
                          n === i ? { ...v, page_from: +e.target.value } : v,
                        ),
                      )
                    }
                  />
                  <input
                    aria-label={`Конец главы ${i + 1}`}
                    type="number"
                    min={c.page_from}
                    value={c.page_to}
                    onChange={(e) =>
                      setChapters(
                        chapters.map((v, n) =>
                          n === i ? { ...v, page_to: +e.target.value } : v,
                        ),
                      )
                    }
                  />
                  <button
                    className="icon-button"
                    aria-label={`Удалить главу ${i + 1}`}
                    onClick={() =>
                      setChapters(chapters.filter((_, n) => i !== n))
                    }
                  >
                    <X size={15} />
                  </button>
                </div>
              ))}
              <div className="inline-actions">
                <button
                  className="button small"
                  onClick={() =>
                    setChapters([
                      ...chapters,
                      {
                        n: chapters.length + 1,
                        title: "Новая глава",
                        page_from: 1,
                        page_to: 1,
                      },
                    ])
                  }
                >
                  <Plus size={14} />
                  Глава
                </button>
                <Submit
                  busy={action.busy}
                  onClick={() =>
                    action.run(async () => {
                      await write(
                        raw + "/outline",
                        {
                          chapters: chapters.map((c, i) => ({
                            ...c,
                            n: i + 1,
                          })),
                        },
                        "PUT",
                      );
                      setEdit(false);
                      await outline.refetch();
                      toast("Оглавление сохранено. Задачу можно возобновить.");
                    })
                  }
                >
                  Сохранить оглавление
                </Submit>
              </div>
            </div>
          ) : (
            <div className="outline-list">
              {outline.data.chapters.map((c) => (
                <div key={c.n}>
                  <span>{c.n.toString().padStart(2, "0")}</span>
                  <strong>{c.title}</strong>
                  <small>
                    стр. {c.page_from}–{c.page_to}
                  </small>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <p className="muted">
          Текст ещё не извлечён. Запустите извлечение или разбор с агентом.
        </p>
      )}
      <div className="section-title">
        <h3>Текст источника</h3>
        <button
          className="text-link"
          disabled={action.busy}
          onClick={() => void read()}
        >
          {text && next.pages ? "Следующий фрагмент" : "Прочитать фрагмент"}
        </button>
      </div>
      {text && <pre className="source-text">{text}</pre>}
    </Modal>
  );
}
