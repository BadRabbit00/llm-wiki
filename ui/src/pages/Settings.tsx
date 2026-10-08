import { useState } from "react";
import { LogOut, Monitor, ShieldCheck, UserRound } from "lucide-react";
import { useAuth } from "../auth";
import { useAPI } from "../api";
import { Badge, ErrorBanner, Heading, Modal } from "../components/common";

export default function Settings() {
  const { actor, logout } = useAuth(),
    health = useAPI<{ version: string; index_commit: string }>("/health"),
    [confirm, setConfirm] = useState(false);
  return (
    <div className="page-enter settings-page">
      <Heading
        eyebrow="ВАШЕ ПРОСТРАНСТВО"
        title="Профиль и подключение"
        description="Доступ к знаниям, состояние вики и управление сеансом."
      />
      <div className="settings-grid">
        <section className="panel settings-card">
          <div className="section-title">
            <h2>
              <UserRound size={20} />
              Ваш профиль
            </h2>
          </div>
          <div className="profile-display">
            <span className="avatar large">
              {(actor?.person || actor?.name || "U").slice(0, 1).toUpperCase()}
            </span>
            <div>
              <h3>{actor?.person || actor?.name}</h3>
              <p>{actor?.name}</p>
            </div>
          </div>
          <dl>
            <dt>Роль</dt>
            <dd>
              <Badge value={actor?.role} />
            </dd>
            <dt>Допуск</dt>
            <dd>
              <Badge value={actor?.clearance} />
            </dd>
            <dt>Тип участника</dt>
            <dd>
              <Badge value={actor?.kind} />
            </dd>
          </dl>
        </section>
        <section className="panel settings-card">
          <div className="section-title">
            <h2>
              <Monitor size={20} />
              Подключение
            </h2>
          </div>
          <ErrorBanner error={health.error} />
          <dl>
            <dt>Вики</dt>
            <dd>
              <span
                className={`connection-pill ${health.error ? "offline" : ""}`}
              >
                <i />
                {health.error
                  ? "Недоступна"
                  : health.isPending
                    ? "Проверяем…"
                    : "На связи"}
              </span>
            </dd>
            <dt>Версия</dt>
            <dd>
              <code>{health.data?.version || "—"}</code>
            </dd>
            <dt>Версия знаний</dt>
            <dd>
              <code>{health.data?.index_commit?.slice(0, 12) || "—"}</code>
            </dd>
            <dt>Адрес пространства</dt>
            <dd>{window.location.origin}</dd>
          </dl>
        </section>
      </div>
      <section className="session-panel">
        <ShieldCheck size={24} />
        <div>
          <h3>Этот сеанс принадлежит вам</h3>
          <p>
            Вход подтверждён через Authentik. Выход завершает сеанс и очищает
            загруженные данные. Для изменения роли обратитесь к администратору.
          </p>
        </div>
        <button className="button" onClick={() => setConfirm(true)}>
          <LogOut size={16} />
          Выйти
        </button>
      </section>
      {confirm && (
        <Modal title="Выйти из пространства" onClose={() => setConfirm(false)}>
          <p>
            Следующий вход пройдёт через Authentik. Незавершённые предложения и
            диалоги сохранятся на сервере.
          </p>
          <div className="modal-footer">
            <button className="button" onClick={() => setConfirm(false)}>
              Остаться
            </button>
            <button className="button primary" onClick={logout}>
              Выйти
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
