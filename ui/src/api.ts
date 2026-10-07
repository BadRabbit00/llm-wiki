import { QueryClient, useQuery } from "@tanstack/react-query";
import type { List } from "./types";

let token = sessionStorage.getItem("wiki.token") || "";
export const credentials = {
  get: () => token,
  set: (value: string) => {
    token = value;
    value
      ? sessionStorage.setItem("wiki.token", value)
      : sessionStorage.removeItem("wiki.token");
  },
};
export class APIError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public hint = "",
  ) {
    super(message);
  }
}
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 20_000, retry: false, refetchOnWindowFocus: true },
  },
});
export async function responseError(response: Response): Promise<never> {
  const body = await response.json().catch(() => ({}));
  if (response.status === 401)
    window.dispatchEvent(new Event("wiki:unauthorized"));
  throw new APIError(
    body.error?.code || "E_REQUEST",
    body.error?.message ||
      (response.status === 502
        ? "Сервис пока недоступен. Попробуйте чуть позже."
        : `Не удалось выполнить запрос (${response.status}).`),
    response.status,
    body.error?.hint,
  );
}
export async function api<T>(
  path: string,
  init: RequestInit = {},
  agent = false,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${credentials.get()}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch((agent ? "/agent-api" : "/api/v1") + path, {
      ...init,
      headers,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new APIError(
      "E_NETWORK",
      "Нет связи с сервером. Проверьте подключение.",
      0,
    );
  }
  if (!response.ok) return responseError(response);
  return response.json();
}
export function useAPI<T>(
  path: string,
  agent = false,
  enabled = true,
  interval?: number,
) {
  return useQuery<T>({
    queryKey: [agent ? "agent" : "wiki", path],
    queryFn: ({ signal }) => api<T>(path, { signal }, agent),
    enabled,
    refetchInterval: interval,
  });
}
export async function all<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  const result: T[] = [];
  let cursor: string | null | undefined;
  do {
    const batch = await api<List<T>>(
      `${path}${path.includes("?") ? "&" : "?"}limit=100${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`,
      { signal },
    );
    result.push(...batch.items);
    cursor = batch.next_cursor;
  } while (cursor);
  return result;
}
export function useAll<T>(path: string, enabled = true) {
  return useQuery({
    queryKey: ["wiki", "all", path],
    queryFn: ({ signal }) => all<T>(path, signal),
    enabled,
  });
}
export function write<T>(
  path: string,
  body: unknown = {},
  method = "POST",
  agent = false,
) {
  return api<T>(path, { method, body: JSON.stringify(body) }, agent);
}
export function invalidate() {
  return queryClient.invalidateQueries();
}
export function params(values: Record<string, string | undefined>) {
  const p = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v) p.set(k, v);
  });
  return p.toString();
}
export async function streamMessage(
  id: string,
  text: string,
  onEvent: (event: string, value: unknown) => void,
  signal?: AbortSignal,
) {
  const response = await fetch(`/agent-api/chat/sessions/${id}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${credentials.get()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!response.ok) return responseError(response);
  if (!response.body) throw new Error("Сервер не вернул поток ответа.");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    received = false;
  const dispatch = (block: string) => {
    const event =
      block
        .split("\n")
        .find((l) => l.startsWith("event:"))
        ?.slice(6)
        .trim() || "message";
    const data = block
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart())
      .join("\n");
    if (data) {
      const value = JSON.parse(data);
      if (event === "error")
        throw new APIError(
          value.error?.code || "E_AGENT",
          value.error?.message || "Не удалось обработать сообщение.",
          500,
          value.error?.hint,
        );
      if (event === "message") received = true;
      onEvent(event, value);
    }
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        dispatch(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
      if (done) {
        if (buffer.trim()) dispatch(buffer);
        break;
      }
    }
    if (!received)
      throw new Error(
        "Соединение прервалось до ответа. Обновите диалог, прежде чем повторять сообщение.",
      );
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
