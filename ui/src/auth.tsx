import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, queryClient } from "./api";
import type { Actor } from "./types";

const Auth = createContext<{
  actor: Actor | null;
  loading: boolean;
  logout: () => void;
}>({ actor: null, loading: true, logout: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [actor, setActor] = useState<Actor | null>(null);
  const [loading, setLoading] = useState(true);
  const logout = () => {
    queryClient.clear();
    const form = document.createElement("form");
    form.method = "POST";
    form.action = "/auth/logout";
    document.body.appendChild(form);
    form.submit();
  };
  useEffect(() => {
    const unauthorized = () => {
      window.location.assign("/auth/login");
    };
    api<Actor>("/whoami")
      .then(setActor)
      .catch(() => setActor(null))
      .finally(() => setLoading(false));
    window.addEventListener("wiki:unauthorized", unauthorized);
    return () => window.removeEventListener("wiki:unauthorized", unauthorized);
  }, []);
  return (
    <Auth.Provider value={{ actor, loading, logout }}>{children}</Auth.Provider>
  );
}

export const useAuth = () => useContext(Auth);
export const canWrite = (actor: Actor | null) =>
  !!actor && actor.role !== "reader";
export const canReview = (actor: Actor | null) =>
  !!actor &&
  actor.kind === "human" &&
  ["reviewer", "admin"].includes(actor.role);
