import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, credentials, queryClient } from "./api";
import type { Actor } from "./types";

const Auth = createContext<{
  actor: Actor | null;
  loading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
}>({ actor: null, loading: true, login: async () => {}, logout: () => {} });
export function AuthProvider({ children }: { children: ReactNode }) {
  const [actor, setActor] = useState<Actor | null>(null),
    [loading, setLoading] = useState(!!credentials.get());
  const logout = () => {
    credentials.set("");
    queryClient.clear();
    setActor(null);
    setLoading(false);
  };
  const login = async (value: string) => {
    credentials.set(value.trim());
    try {
      const user = await api<Actor>("/whoami");
      queryClient.clear();
      setActor(user);
    } catch (error) {
      credentials.set("");
      throw error;
    }
  };
  useEffect(() => {
    if (credentials.get())
      api<Actor>("/whoami")
        .then(setActor)
        .catch(logout)
        .finally(() => setLoading(false));
    window.addEventListener("wiki:unauthorized", logout);
    return () => window.removeEventListener("wiki:unauthorized", logout);
  }, []);
  return (
    <Auth.Provider value={{ actor, loading, login, logout }}>
      {children}
    </Auth.Provider>
  );
}
export const useAuth = () => useContext(Auth);
export const canWrite = (actor: Actor | null) =>
  !!actor && actor.role !== "reader";
export const canReview = (actor: Actor | null) =>
  !!actor &&
  actor.kind === "human" &&
  ["reviewer", "admin"].includes(actor.role);
