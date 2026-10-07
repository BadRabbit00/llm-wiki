import React, { Component, Suspense, lazy, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import "@fontsource/manrope/cyrillic-400.css";
import "@fontsource/manrope/cyrillic-500.css";
import "@fontsource/manrope/cyrillic-600.css";
import "@fontsource/manrope/cyrillic-700.css";
import "@fontsource/manrope/latin-400.css";
import "@fontsource/manrope/latin-500.css";
import "@fontsource/manrope/latin-600.css";
import "@fontsource/manrope/latin-700.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "./styles.css";
import { queryClient } from "./api";
import { AuthProvider, useAuth } from "./auth";
import { Empty, Loading, ToastProvider } from "./components/common";
import Layout from "./components/Layout";
import Login from "./pages/Login";
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Knowledge = lazy(() => import("./pages/Knowledge"));
const PageDetail = lazy(() => import("./pages/PageDetail"));
const Review = lazy(() => import("./pages/Review"));
const ProposalDetail = lazy(() => import("./pages/ProposalDetail"));
const Chat = lazy(() => import("./pages/Chat"));
const Sources = lazy(() => import("./pages/Sources"));
const Jobs = lazy(() => import("./pages/Jobs"));
const Graph = lazy(() => import("./pages/Graph"));
const Policies = lazy(() => import("./pages/Policies"));
const Settings = lazy(() => import("./pages/Settings"));
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="fatal-error">
        <Empty
          title="Не удалось открыть экран"
          text="Попробуйте обновить страницу. Ваши сохранённые данные остаются на сервере."
        >
          <button className="button primary" onClick={() => location.reload()}>
            Обновить страницу
          </button>
        </Empty>
      </div>
    ) : (
      this.props.children
    );
  }
}
function App() {
  const { actor, loading } = useAuth();
  if (loading)
    return (
      <div className="app-loading">
        <Loading lines={3} />
      </div>
    );
  if (!actor) return <Login />;
  return (
    <Suspense
      fallback={
        <div className="app-loading">
          <Loading lines={4} />
        </div>
      }
    >
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="pages" element={<Knowledge />} />
          <Route path="rules" element={<Knowledge rules />} />
          <Route path="pages/:id" element={<PageDetail />} />
          <Route path="proposals" element={<Review />} />
          <Route path="proposals/:id" element={<ProposalDetail />} />
          <Route path="chat" element={<Chat />} />
          <Route path="chat/:id" element={<Chat />} />
          <Route path="sources" element={<Sources />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="graph" element={<Graph />} />
          <Route path="policies" element={<Policies />} />
          <Route path="settings" element={<Settings />} />
          <Route
            path="*"
            element={
              <Empty title="Такой страницы здесь нет">
                <Link className="button" to="/">
                  Вернуться в пространство
                </Link>
              </Empty>
            }
          />
        </Route>
      </Routes>
    </Suspense>
  );
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Boundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <ToastProvider>
              <App />
            </ToastProvider>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </Boundary>
  </React.StrictMode>,
);
