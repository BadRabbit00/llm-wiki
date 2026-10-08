import { useState } from "react";
import { invalidate, useAPI, write } from "../api";
import type { Profile } from "../types";
import { ErrorBanner, Modal, Submit, useAction, useToast } from "./common";

interface Limits {
  enabled: boolean;
  max_files: number;
  max_file_bytes: number;
  max_total_bytes: number;
}

export function DocsAudit({ onClose }: { onClose: () => void }) {
  const limits = useAPI<Limits>("/docs-audit/config", true);
  const profiles = useAPI<Profile[]>("/profiles");
  const [project, setProject] = useState("");
  const [profile, setProfile] = useState("");
  const [scopes, setScopes] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const action = useAction();
  const toast = useToast();
  const start = () =>
    action.run(async () => {
      const bounds = limits.data;
      if (!bounds?.enabled)
        throw new Error("Сверка документации выключена администратором.");
      if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(project))
        throw new Error(
          "Имя проекта: до 64 строчных латинских букв, цифр и дефисов.",
        );
      if (!profile) throw new Error("Выберите профиль политик.");
      if (!files.length || files.length > bounds.max_files)
        throw new Error(`Выберите от 1 до ${bounds.max_files} файлов .md.`);
      if (
        files.reduce((sum, file) => sum + file.size, 0) > bounds.max_total_bytes
      )
        throw new Error("Превышен суммарный размер документации.");
      const paths = new Set<string>();
      const documents = [];
      for (const file of files) {
        const path = file.webkitRelativePath || file.name;
        if (
          !path.endsWith(".md") ||
          path.startsWith("/") ||
          /[\\:\x00-\x1f]/.test(path) ||
          path.split("/").some((part) => ["", ".", ".."].includes(part)) ||
          paths.has(path)
        )
          throw new Error("Нужны уникальные относительные пути .md без .. .");
        if (file.size > bounds.max_file_bytes)
          throw new Error(`${path}: файл превышает 256 КиБ.`);
        paths.add(path);
        const text = new TextDecoder("utf-8", { fatal: true }).decode(
          await file.arrayBuffer(),
        );
        documents.push({ path, text });
      }
      await write(
        "/jobs/docs-audit",
        {
          project,
          profile,
          scopes: scopes
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          files: documents,
        },
        "POST",
        true,
      );
      await invalidate();
      toast("Сверка документации запущена. Находки появятся во входящих.");
      onClose();
    });
  return (
    <Modal title="Сверить документацию проекта" onClose={onClose}>
      <p className="modal-description">
        Выберите папку docs. Агент сравнит документацию с политиками выбранного
        профиля и отправит находки на ревью.
      </p>
      <ErrorBanner error={limits.error || profiles.error || action.error} />
      {limits.data && !limits.data.enabled && (
        <p className="callout">
          Сверка документации выключена администратором.
        </p>
      )}
      <label>
        Проект
        <input
          value={project}
          onChange={(event) => setProject(event.target.value)}
          placeholder="orders-platform"
          maxLength={64}
        />
      </label>
      <label>
        Профиль
        <select
          value={profile}
          onChange={(event) => setProfile(event.target.value)}
        >
          <option value="">Выберите профиль</option>
          {profiles.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title || p.id}
            </option>
          ))}
        </select>
      </label>
      <label>
        Области через запятую (необязательно)
        <input
          value={scopes}
          onChange={(event) => setScopes(event.target.value)}
          placeholder="По умолчанию — области профиля"
        />
      </label>
      <label>
        Папка документации
        <input
          type="file"
          multiple
          accept=".md"
          {...{ webkitdirectory: "" }}
          onChange={(event) =>
            setFiles(
              Array.from(event.target.files || []).filter((file) =>
                file.name.endsWith(".md"),
              ),
            )
          }
        />
      </label>
      <p>
        Выбрано файлов: {files.length}. До {limits.data?.max_files || 200}{" "}
        файлов, 256 КиБ каждый,{" "}
        {Math.floor((limits.data?.max_total_bytes || 26214400) / 1048576)} МиБ
        всего. Удалите секреты перед загрузкой.
      </p>
      <div className="modal-footer">
        <Submit
          busy={action.busy}
          disabled={
            !limits.data?.enabled || !files.length || !profile || !project
          }
          onClick={() => void start()}
        >
          Запустить сверку
        </Submit>
      </div>
    </Modal>
  );
}
