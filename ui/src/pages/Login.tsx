import { useState } from "react";
import {
  ArrowRight,
  Fingerprint,
  GitBranch,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useAuth } from "../auth";
import { ErrorBanner, Submit, useAction } from "../components/common";
import { Mark } from "../components/Layout";

export default function Login() {
  const [token, setToken] = useState(""),
    { login } = useAuth(),
    action = useAction();
  return (
    <div className="login-page">
      <section className="login-story">
        <a className="brand" href="/">
          <Mark />
          <span>wiki.</span>
        </a>
        <div className="login-story-content">
          <div className="eyebrow">
            <span className="dot" /> КОМАНДНАЯ ПАМЯТЬ
          </div>
          <h1>
            Хорошие решения
            <br />
            не должны
            <br />
            <em>забываться.</em>
          </h1>
          <p>
            Собирайте знания, договаривайтесь о правилах
            <br />и давайте агентам правильный контекст.
          </p>
          <div className="login-constellation" aria-hidden="true">
            <svg viewBox="0 0 520 230">
              <path
                d="M90 90 C170 90 140 175 260 135 S340 30 420 75 M260 135 L370 205 M260 135 L185 30"
                fill="none"
                stroke="currentColor"
                strokeDasharray="4 6"
              />
            </svg>
            <div className="constellation-note note-1">
              <GitBranch size={17} />
              <span>Решение команды</span>
            </div>
            <div className="constellation-note note-2">
              <ShieldCheck size={17} />
              <span>Проверенное правило</span>
              <i />
            </div>
            <div className="constellation-note note-3">
              <Sparkles size={17} />
              <span>Контекст для агента</span>
            </div>
            <span className="constellation-point point-1" />
            <span className="constellation-point point-2" />
          </div>
        </div>
        <div className="login-story-footer">
          <span>ОДНО ПРОСТРАНСТВО. ОБЩЕЕ ПОНИМАНИЕ.</span>
          <span>01 — ∞</span>
        </div>
      </section>
      <section className="login-form-side">
        <div className="login-form">
          <div className="login-icon">
            <Fingerprint size={30} />
          </div>
          <span className="eyebrow">ДОБРО ПОЖАЛОВАТЬ</span>
          <h2>Вернёмся к важному</h2>
          <p>
            Войдите в пространство с токеном,
            <br />
            который выдал администратор.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action.run(() => login(token));
            }}
          >
            <label className="field">
              Токен доступа
              <div className="input-icon">
                <LockKeyhole size={17} />
                <input
                  type="password"
                  autoComplete="off"
                  autoFocus
                  placeholder="Вставьте ваш токен"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  required
                />
              </div>
            </label>
            <ErrorBanner error={action.error} />
            <Submit
              busy={action.busy}
              disabled={!token.trim()}
              className="button primary login-submit"
            >
              Войти в пространство <ArrowRight size={18} />
            </Submit>
          </form>
          <div className="login-note">
            <ShieldCheck size={16} />
            <span>
              Токен сохраняется только до закрытия вкладки.
              <br />У каждого участника — свой уровень доступа.
            </span>
          </div>
        </div>
        <small className="login-bottom">
          Знания принадлежат вашей команде.
        </small>
      </section>
    </div>
  );
}
