import { useEffect, useState } from "react";
import {
  CheckCircle2,
  CircleDashed,
  Download,
  ExternalLink,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { queryClient, updater, useUpdater } from "../api";
import type { ReleaseImage, UpdateOperation, UpdaterStatus } from "../types";
import { ErrorBanner, Modal, Submit, fullDate, useAction } from "./common";

const repository = "https://github.com/BadRabbit00/llm-wiki";

const steps: Record<string, string> = {
  pull: "Загрузка образа",
  verify: "Проверка подписи",
  "jobs-before": "Задачи агента до обновления",
  stop: "Мягкая остановка служб",
  archive: "Резервная копия данных",
  switch: "Переключение версии",
  migrate: "Миграции и переиндексация",
  start: "Запуск служб",
  health: "Проверка работоспособности",
  "jobs-after": "Задачи агента после обновления",
  timer: "Расписание резервных копий",
  resume: "Возврат служб",
  rollback: "Откат к прежней версии",
  prune: "Старые копии перед обновлениями",
};
const outcomes: Record<UpdateOperation["state"], string> = {
  running: "Идёт обновление",
  succeeded: "Обновлено",
  rolled_back: "Не удалось — вернули прежнюю версию",
  failed: "Не удалось",
  interrupted: "Прервано",
};

function version(image?: ReleaseImage | null) {
  if (!image?.digest) return "—";
  return image.tag || image.digest.slice(7, 19);
}

// What changed between two builds: their commits if both are known, else the tag.
function changesLink(from: ReleaseImage, to: ReleaseImage) {
  return from.revision && to.revision
    ? `${repository}/compare/${from.revision}...${to.revision}`
    : `${repository}/tree/${to.tag}`;
}

// The interface itself restarts during an update: while it is gone the page waits
// for /healthz, then reloads to pick up the new build and the update's outcome.
function useWaitForRestart(active: boolean) {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    const tick = async () => {
      try {
        const status = await updater<UpdaterStatus>("/v1/status");
        setOffline(false);
        queryClient.setQueryData(["updater", "/v1/status"], status);
        if (status.operation?.state !== "running") {
          window.location.reload();
          return;
        }
      } catch {
        setOffline(true);
      }
      if (!stopped) window.setTimeout(tick, 2000);
    };
    const timer = window.setTimeout(tick, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [active]);
  return offline;
}

function Steps({ operation }: { operation: UpdateOperation }) {
  return (
    <ol className="update-steps">
      {(operation.steps || []).map((step) => (
        <li key={step.name} className={`update-step ${step.status}`}>
          {step.status === "done" ? (
            <CheckCircle2 size={16} />
          ) : step.status === "failed" ? (
            <XCircle size={16} />
          ) : (
            <CircleDashed size={16} className="spin" />
          )}
          <span>{steps[step.name] || step.name}</span>
          {step.detail && step.status === "failed" && (
            <small>{step.detail}</small>
          )}
        </li>
      ))}
    </ol>
  );
}

function Outcome({ operation }: { operation: UpdateOperation }) {
  const paused = operation.jobs_before?.length || 0,
    resumed = operation.jobs_after?.length || 0;
  return (
    <div className={`update-outcome ${operation.state}`}>
      <strong>
        {outcomes[operation.state]}: {version(operation.from)} →{" "}
        {version(operation.to)}
      </strong>
      <p>
        {operation.started_by} · {fullDate(operation.started_at)}
        {operation.finished_at && ` — ${fullDate(operation.finished_at)}`}
      </p>
      {operation.error && <p className="update-error">{operation.error}</p>}
      {operation.state === "succeeded" && paused > 0 && (
        <p>
          Задач агента на паузе перед обновлением: {paused}; продолжаются после
          него: {resumed}.
        </p>
      )}
      {operation.archive && (
        <p>
          Копия данных перед обновлением: <code>{operation.archive}</code>
        </p>
      )}
      <Steps operation={operation} />
    </div>
  );
}

export default function Updates() {
  const status = useUpdater<UpdaterStatus>("/v1/status"),
    action = useAction(),
    [confirm, setConfirm] = useState(false),
    [understood, setUnderstood] = useState(false),
    [watching, setWatching] = useState(true),
    data = status.data,
    offer = data?.available,
    running = data?.operation?.state === "running",
    offline = useWaitForRestart(running);
  // The topbar badge links here.
  useEffect(() => {
    if (data && window.location.hash === "#updates")
      document.getElementById("updates")?.scrollIntoView({ block: "start" });
  }, [data]);
  const send = (path: string, method: string, body?: object) =>
    action.run(async () => {
      const next = await updater<UpdaterStatus>(path, {
        method,
        body: body ? JSON.stringify(body) : undefined,
      });
      queryClient.setQueryData(["updater", "/v1/status"], next);
    });
  return (
    <section className="panel settings-card updates-card" id="updates">
      <div className="section-title">
        <h2>
          <Download size={20} />
          Обновления
        </h2>
      </div>
      <ErrorBanner error={status.error || action.error} />
      {data && (
        <>
          <dl>
            <dt>Установлено</dt>
            <dd>
              <code>{version(data.current)}</code>
            </dd>
            <dt>Канал</dt>
            <dd>
              <select
                aria-label="Канал обновлений"
                value={data.channel}
                disabled={running || action.busy}
                onChange={(e) =>
                  void send("/v1/channel", "PUT", { channel: e.target.value })
                }
              >
                <option value="release">Релизы</option>
                <option value="beta">Бета-версии</option>
              </select>
            </dd>
            <dt>Последняя проверка</dt>
            <dd>
              {data.checked_at ? fullDate(data.checked_at) : "ещё не было"}
            </dd>
          </dl>
          {data.check_error && (
            <div className="error-banner" role="alert">
              <div>
                <strong>Проверка не удалась</strong>
                <p>{data.check_error}</p>
              </div>
            </div>
          )}
          {data.available && !running ? (
            <div className="update-offer">
              <div>
                <strong>Доступна версия {data.available.tag}</strong>
                <a
                  href={changesLink(data.current, data.available)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Что изменилось <ExternalLink size={13} />
                </a>
              </div>
              <button
                className="button primary"
                onClick={() => {
                  setUnderstood(false);
                  setConfirm(true);
                }}
              >
                <Download size={16} />
                Обновить
              </button>
            </div>
          ) : (
            !running && (
              <p className="muted">Установлена последняя версия канала.</p>
            )
          )}
          <div className="update-actions">
            <Submit
              className="button"
              busy={action.busy}
              disabled={running}
              onClick={() => void send("/v1/check", "POST")}
            >
              {!action.busy && <RefreshCw size={16} />}
              Проверить сейчас
            </Submit>
          </div>
          {data.operation && <Outcome operation={data.operation} />}
        </>
      )}
      {confirm && offer && (
        <Modal
          title={`Обновить до ${offer.tag}`}
          onClose={() => setConfirm(false)}
        >
          <p>
            Службы остановятся на несколько минут, интерфейс перезапустится.
            Агент допишет открытые ответы и поставит задачи на паузу; после
            обновления они продолжатся сами. Перед переключением данные
            копируются, и если новая версия не запустится, система вернётся к
            прежней.
          </p>
          <label className="check-label important-confirm">
            <input
              type="checkbox"
              checked={understood}
              onChange={(e) => setUnderstood(e.target.checked)}
            />
            <span>Сейчас подходящее время: работа команды прервётся.</span>
          </label>
          <div className="modal-footer">
            <button className="button" onClick={() => setConfirm(false)}>
              Отмена
            </button>
            <Submit
              busy={action.busy}
              disabled={!understood}
              onClick={() =>
                void send("/v1/apply", "POST", { digest: offer.digest }).then(
                  () => setConfirm(false),
                )
              }
            >
              Обновить
            </Submit>
          </div>
        </Modal>
      )}
      {running && watching && data?.operation && (
        <Modal
          title={`Обновление до ${data.operation.to.tag}`}
          onClose={() => setWatching(false)}
        >
          <p>
            {offline
              ? "Интерфейс перезапускается. Страница обновится сама, как только он вернётся."
              : "Не закрывайте страницу: она покажет итог, когда обновление закончится."}
          </p>
          <Steps operation={data.operation} />
        </Modal>
      )}
    </section>
  );
}
