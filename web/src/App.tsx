import {
  ArrowClockwise,
  CalendarBlank,
  Database,
  Moon,
  ShieldCheck,
  SidebarSimple,
  Sun,
  UploadSimple,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { fetchDashboard } from "./api/client";
import type { DashboardData } from "./api/types";
import { Dashboard } from "./components/Dashboard";
import { ReviewImportPanel } from "./components/ReviewImportPanel";

type Theme = "light" | "dark";

function loadTheme(): Theme {
  try {
    return localStorage.getItem("guardian-theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function timestampLabel(value: string | null | undefined): string {
  if (!value) return "Update time unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function App() {
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const requestRef = useRef<AbortController | null>(null);

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("guardian-theme", theme);
    } catch {
      // Theme persistence is optional; no business data is stored in the browser.
    }
  }, [theme]);

  const load = useCallback(async (refresh = false) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError("");
    try {
      setData(await fetchDashboard(controller.signal));
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "The dashboard request failed.");
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void load();
    return () => requestRef.current?.abort();
  }, [load]);

  const isEmpty = data?.dataState === "empty";
  const hasNoProductGroups = data !== null && data.dataState !== "empty" && data.products.length === 0;

  return (
    <div className={`app-shell ${sidebarCollapsed ? "is-sidebar-collapsed" : ""}`}>
      <a className="skip-link" href="#main-content">Skip to dashboard</a>
      <aside className="sidebar">
        <div className="brand"><ShieldCheck size={25} weight="fill" aria-hidden="true" /><span>Guardian</span></div>
        <nav className="sidebar-nav" aria-label="Primary navigation">
          <a className="nav-item is-active" href="#main-content" aria-current="page"><ShieldCheck size={20} weight="fill" /><span>Command Center</span></a>
          <a className="nav-item" href="#review-import"><UploadSimple size={20} /><span>Import reviews</span></a>
        </nav>
        <div className="sidebar-footer">
          <button className="nav-item sidebar-collapse" type="button" onClick={() => setSidebarCollapsed((value) => !value)} aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <SidebarSimple size={20} /><span>Collapse</span>
          </button>
        </div>
      </aside>

      <header className="topbar">
        <div><span className="topbar-kicker">Voice of customer</span><h1>Command Center</h1></div>
        <div className="topbar-actions">
          <button className="refresh-button" type="button" onClick={() => void load(true)} disabled={loading || refreshing} aria-label="Refresh dashboard">
            <ArrowClockwise size={17} className={refreshing ? "is-spinning" : ""} /><span>{refreshing ? "Refreshing" : "Refresh"}</span>
          </button>
          <button className="theme-toggle" type="button" onClick={() => setTheme((value) => value === "light" ? "dark" : "light")} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}>
            {theme === "light" ? <Sun size={17} weight="fill" /> : <Moon size={17} weight="fill" />}<span>{theme === "light" ? "Light" : "Dark"}</span>
          </button>
          <div className="topbar-date" aria-label="Last dashboard update"><CalendarBlank size={18} /><span>{timestampLabel(data?.lastUpdated ?? data?.asOf)}</span></div>
          {data && <div className={`api-status api-status--${data.overallHealth}`}><i aria-hidden="true" /><span>{data.mode === "demo" ? "Server demo mode" : data.overallHealth}</span></div>}
        </div>
      </header>

      <main className="dashboard" id="main-content">
        {loading && !data && (
          <section className="loading-state" aria-busy="true" aria-label="Loading dashboard">
            <div className="loading-state__title" /><div className="loading-state__metric" /><div className="loading-state__grid"><span /><span /><span /></div>
            <p>Loading real dashboard data…</p>
          </section>
        )}

        {error && !data && (
          <section className="error-state" role="alert">
            <span className="error-state__icon"><WarningCircle size={30} weight="fill" /></span>
            <span className="eyebrow">Backend unavailable</span>
            <h2>Dashboard data could not be loaded</h2>
            <p>{error}</p>
            <p className="error-state__truth">No cached fixture or fabricated fallback is being shown.</p>
            <button className="primary-button" type="button" onClick={() => void load()}>Retry dashboard</button>
          </section>
        )}

        {data && error && (
          <section className="truth-banner truth-banner--error" role="alert"><WarningCircle size={20} /><div><strong>Refresh failed</strong><p>{error}. The last successful server response remains visible.</p></div></section>
        )}

        {data && isEmpty && (
          <section className="empty-data-state">
            <span className="empty-data-state__icon"><Database size={30} /></span>
            <span className="eyebrow">No dashboard data</span>
            <h2>No product-attributed feedback is available</h2>
            <p>{data.messages[0] ?? "The backend has not returned enough product-linked records to build this dashboard."}</p>
            <div className="empty-data-state__coverage">
              <span><strong>{data.coverage.feedbackItems.toLocaleString()}</strong> feedback items</span>
              <span><strong>{data.coverage.analyzedItems.toLocaleString()}</strong> analyzed</span>
              <span><strong>{data.coverage.productAttributedItems.toLocaleString()}</strong> product attributed</span>
            </div>
            <p className="error-state__truth">Product names, metrics, and incidents are not inferred when the API has insufficient data.</p>
          </section>
        )}

        {data && hasNoProductGroups && (
          <section className="empty-data-state empty-data-state--partial" role="status">
            <span className="empty-data-state__icon"><Database size={30} /></span>
            <span className="eyebrow">{data.dataState} coverage</span>
            <h2>No Guardian product groups are available yet</h2>
            <p>{data.messages[0] ?? "The backend returned coverage information, but no grouped product data for this window."}</p>
            <div className="empty-data-state__coverage">
              <span><strong>{data.coverage.feedbackItems.toLocaleString()}</strong> feedback items</span>
              <span><strong>{data.coverage.analyzedItems.toLocaleString()}</strong> analyzed</span>
              <span><strong>{data.coverage.productAttributedItems.toLocaleString()}</strong> product attributed</span>
            </div>
            <p className="error-state__truth">No product catalog values or incidents are being inferred.</p>
          </section>
        )}

        {data && !isEmpty && !hasNoProductGroups && <Dashboard data={data} />}

        <section className="operator-section" aria-labelledby="operator-title">
          <h2 className="visually-hidden" id="operator-title">Import reviews</h2>
          <ReviewImportPanel onImported={() => load(true)} />
        </section>
      </main>
    </div>
  );
}
