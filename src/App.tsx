import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  Alarm,
  ArrowRight,
  CalendarBlank,
  CaretRight,
  Chats,
  CheckCircle,
  Clock,
  Cube,
  DeviceMobile,
  GlobeHemisphereWest,
  Headset,
  Moon,
  Package,
  Pulse,
  ShieldCheck,
  SidebarSimple,
  SquaresFour,
  Storefront,
  Sun,
  TrendDown,
  TrendUp,
  WarningCircle,
} from "@phosphor-icons/react";
import { InvestigationDrawer, type CreatedAction } from "./components/InvestigationDrawer";
import { ProductFilter } from "./components/ProductFilter";
import { FocusedDashboard } from "./components/FocusedDashboard";
import { PortfolioOverview } from "./components/PortfolioOverview";
import {
  PRODUCTS,
  SOURCE_LABELS,
  deriveDashboard,
  formatPercent,
  formatVelocity,
  normalizeProductIds,
  parseProductSelection,
  serializeProductSelection,
  type ProductId,
  type SourceKey,
} from "./data/dashboard";

const NAV_ITEMS = [
  { label: "Command Center", icon: ShieldCheck, active: true },
];

const SOURCE_ICONS: Record<SourceKey, typeof DeviceMobile> = {
  app: DeviceMobile,
  marketplace: Storefront,
  service: Headset,
  social: GlobeHemisphereWest,
};

type Theme = "light" | "dark";

function loadTheme(): Theme {
  try {
    return localStorage.getItem("guardian-theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function loadActions(): CreatedAction[] {
  try {
    const value = localStorage.getItem("guardian-demo-actions");
    const parsed: unknown = value ? JSON.parse(value) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is CreatedAction => {
      if (!item || typeof item !== "object") return false;
      const candidate = item as Partial<CreatedAction>;
      return (
        typeof candidate.id === "string" &&
        typeof candidate.signalId === "string" &&
        Array.isArray(candidate.productIds) &&
        candidate.productIds.every((id) => typeof id === "string") &&
        typeof candidate.scopeLabel === "string" &&
        typeof candidate.owner === "string" &&
        typeof candidate.dueDate === "string" &&
        candidate.status === "Open" &&
        typeof candidate.createdAt === "string"
      );
    });
  } catch {
    return [];
  }
}

function formatGap(value: number | null) {
  if (value === null) return "—";
  return `${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    signDisplay: "always",
  }).format(value)}pp`;
}

export function App() {
  const [selectedIds, setSelectedIds] = useState<ProductId[]>(() =>
    parseProductSelection(window.location.search),
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [actions, setActions] = useState<CreatedAction[]>(loadActions);
  const data = useMemo(() => deriveDashboard(selectedIds), [selectedIds]);

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("guardian-theme", theme);
    } catch {
      // Light mode remains the safe default when browser storage is unavailable.
    }
  }, [theme]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("products", serializeProductSelection(selectedIds));
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [selectedIds]);

  useEffect(() => {
    try {
      localStorage.setItem("guardian-demo-actions", JSON.stringify(actions));
    } catch {
      // The dashboard remains fully usable when browser storage is unavailable.
    }
  }, [actions]);

  const changeProducts = (ids: ProductId[]) => {
    setSelectedIds(normalizeProductIds(ids));
  };

  const createAction = (action: CreatedAction) => {
    setActions((current) => [
      action,
      ...current.filter(
        (item) =>
          item.signalId !== action.signalId || item.productIds.join(",") !== action.productIds.join(","),
      ),
    ]);
  };

  const topHypothesis = data.hypotheses[0];
  const guardianShare = data.complaintShare;
  const visibleActions = actions.filter((action) =>
    action.productIds.some((productId) => selectedIds.includes(productId)),
  );
  const hasSeededAlert = data.status === "critical" || data.status === "watch";

  return (
    <div className={`app-shell ${sidebarCollapsed ? "is-sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={25} weight="fill" aria-hidden="true" />
          <span>Guardian</span>
        </div>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.label}
                className={`nav-item ${item.active ? "is-active" : ""}`}
                type="button"
                aria-current={item.active ? "page" : undefined}
                aria-disabled={!item.active}
                tabIndex={item.active ? 0 : -1}
              >
                <Icon size={20} weight={item.active ? "fill" : "regular"} aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <button
            className="nav-item sidebar-collapse"
            type="button"
            onClick={() => setSidebarCollapsed((value) => !value)}
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <SidebarSimple size={20} aria-hidden="true" />
            <span>Collapse</span>
          </button>
        </div>
      </aside>

      <header className="topbar">
        <h1>Command Center</h1>
        <div className="topbar-actions">
          <button
            className="theme-toggle"
            type="button"
            onClick={() => setTheme((current) => (current === "light" ? "dark" : "light"))}
            aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
            title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
          >
            {theme === "light" ? (
              <Sun size={17} weight="fill" aria-hidden="true" />
            ) : (
              <Moon size={17} weight="fill" aria-hidden="true" />
            )}
            <span>{theme === "light" ? "Light" : "Dark"}</span>
          </button>
          <div className="topbar-date" aria-label="Current demo date">
            <CalendarBlank size={18} aria-hidden="true" />
            <span>11 Jul 2026</span>
          </div>
          <div className="demo-status">
            <span>Synthetic demo data</span>
            <i aria-hidden="true" />
          </div>
        </div>
      </header>

      <main className="dashboard">
        <section className="portfolio-toolbar" aria-label="Product portfolio scope">
          <div>
            <span className="eyebrow">Current view</span>
            <strong>Guardian customer feedback portfolio</strong>
          </div>
          <ProductFilter selectedIds={selectedIds} onChange={changeProducts} />
        </section>
        {data.selectedProducts.length > 0 && (
          selectedIds.length === PRODUCTS.length ? (
            <PortfolioOverview
              data={data}
              onOpenIncident={(ids) => changeProducts(ids)}
              onSelectProduct={(id) => changeProducts([id])}
              onInvestigateProduct={(id) => {
                changeProducts([id]);
                setDrawerOpen(true);
              }}
            />
          ) : (
            <>
              <button className="back-to-portfolio" type="button" onClick={() => changeProducts(PRODUCTS.map((product) => product.id))}>
                ← Back to portfolio overview
              </button>
              <FocusedDashboard
                data={data}
                onInvestigate={(ids) => {
                  changeProducts(ids);
                  setDrawerOpen(true);
                }}
                onSelectProduct={(id) => changeProducts([id])}
              />
            </>
          )
        )}
        <details className="detail-drawer">
          <summary>
            <span>
              <strong>Detailed evidence and activity</strong>
              <small>Open the original investigation workspace</small>
            </span>
            <ArrowRight size={17} />
          </summary>
          <div className="detail-drawer__grid">
        <section className="main-column">
          {data.selectedProducts.length === 0 ? (
            <EmptyCohort onShowAll={() => changeProducts(PRODUCTS.map((product) => product.id))} />
          ) : (
            <>
              <section className="morning-brief">
                <div className="brief-label">
                  <Pulse size={18} aria-hidden="true" />
                  <span>Morning Brief</span>
                  <span className={`status-dot status-dot--${data.status}`} />
                  <strong>{data.status}</strong>
                </div>

                <div className="hero-signal">
                  <div className={`hero-signal__icon hero-signal__icon--${data.status}`}>
                    {data.status === "improving" ? (
                      <TrendDown size={31} weight="bold" aria-hidden="true" />
                    ) : (
                      <TrendUp size={31} weight="bold" aria-hidden="true" />
                    )}
                  </div>
                  <div>
                    <h2>{data.headline}</h2>
                    <p>
                      Compared with the previous 28-day baseline · {data.scopeLabel}
                    </p>
                  </div>
                </div>

                <div className="metric-strip">
                  <Metric
                    value={String(data.currentComplaints)}
                    label={`of ${data.currentReviews} reviews`}
                    detail="mention packaging in the last 72h"
                    tone="critical"
                  />
                  <Metric
                    value={formatPercent(data.complaintShare)}
                    label="complaint share"
                    detail={`vs ${formatPercent(data.baselineShare)} baseline`}
                    tone="critical"
                  />
                  <Metric
                    value={formatVelocity(data.velocity)}
                    label="issue velocity"
                    detail="current share vs baseline"
                  />
                  <Metric
                    value={`${(data.sentimentDelta ?? 0) > 0 ? "+" : ""}${Math.round(data.sentimentDelta ?? 0)}%`}
                    label="overall sentiment"
                    detail="change inside selected cohort"
                    tone={(data.sentimentDelta ?? 0) >= 0 ? "positive" : "critical"}
                  />
                </div>
              </section>

              <section className="signal-activity">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">Real-time signal feed</span>
                    <h3>Latest signal activity</h3>
                  </div>
                  <span className="section-meta"><Clock size={15} /> Last 72 hours</span>
                </div>
                <div className="activity-list">
                  {data.activities.slice(0, 4).map((activity) => {
                    const product = PRODUCTS.find((item) => item.id === activity.productId);
                    const SourceIcon = SOURCE_ICONS[activity.source];
                    return (
                      <article className="activity-row" key={activity.id}>
                        <time>{activity.timeLabel}</time>
                        <span className="activity-source" title={SOURCE_LABELS[activity.source]}>
                          <SourceIcon size={17} aria-hidden="true" />
                        </span>
                        <div className="activity-copy">
                          <strong>{activity.issue}</strong>
                          <span>{product?.shortName} · {activity.detail}</span>
                        </div>
                        <strong className="activity-delta">{activity.delta}</strong>
                      </article>
                    );
                  })}
                </div>
              </section>

              <section className="context-grid">
                <div className="affected-products">
                  <div className="section-heading section-heading--compact">
                    <div>
                      <span className="eyebrow">Scope</span>
                      <h3>Affected products</h3>
                    </div>
                    <span>{data.affectedProducts.length}</span>
                  </div>
                  <div className="product-list">
                    {data.affectedProducts.map((product) => (
                      <button
                        className="product-row"
                        type="button"
                        key={product.id}
                        onClick={() => changeProducts([product.id])}
                      >
                        <span className="product-row__icon"><Package size={17} /></span>
                        <span className="product-row__copy">
                          <strong>{product.shortName}</strong>
                          <small>{product.sku} · {product.category}</small>
                        </span>
                        <span className="product-row__metric">
                          <strong>{product.current.complaints}</strong>
                          <small>{formatPercent((product.current.complaints / product.current.reviews) * 100)}</small>
                        </span>
                        <CaretRight size={15} />
                      </button>
                    ))}
                  </div>
                </div>

                <div className="customer-voice">
                  <div className="section-heading section-heading--compact">
                    <div>
                      <span className="eyebrow">Evidence</span>
                      <h3>What customers are saying</h3>
                    </div>
                    <span>{data.evidence.filter((item) => item.stance === "support").length} samples</span>
                  </div>
                  <div className="quote-list">
                    {data.evidence.filter((item) => item.stance === "support").slice(0, 4).map((item) => {
                      const product = PRODUCTS.find((candidate) => candidate.id === item.productId);
                      return (
                        <blockquote key={item.id}>
                          <p>“{item.quote}”</p>
                          <footer>{product?.shortName} · {SOURCE_LABELS[item.source]}</footer>
                        </blockquote>
                      );
                    })}
                  </div>
                </div>
              </section>

              <section className="competitor-strip">
                <div className="competitor-strip__title">
                  <span>Competitor context</span>
                  <small>Same product peer cohort</small>
                </div>
                {data.competitors.map((competitor) => {
                  const gap =
                    guardianShare !== null && competitor.share !== null
                      ? guardianShare - competitor.share
                      : null;
                  return (
                    <div className="competitor" key={competitor.retailer}>
                      <i className={`competitor__dot competitor__dot--${competitor.retailer}`} />
                      <span>
                        <strong>{competitor.retailer === "hasaki" ? "Hasaki" : "Watsons"}</strong>
                        <small>{competitor.complaints}/{competitor.reviews} packaging complaints</small>
                      </span>
                      <strong className="competitor__gap">{formatGap(gap)}</strong>
                    </div>
                  );
                })}
                <button className="text-link" type="button">
                  View benchmark <ArrowRight size={15} />
                </button>
              </section>
            </>
          )}
        </section>

        <aside className="evidence-column">
          <div className="evidence-head">
            <h2>Evidence</h2>
            <span>72 hours</span>
          </div>

          {data.selectedProducts.length ? (
            <>
              <section className="hypothesis-summary">
                <span className="eyebrow">Root-cause hypothesis</span>
                <div className="hypothesis-title-row">
                  <h3>{topHypothesis?.title ?? "Not enough evidence"}</h3>
                  {topHypothesis && (
                    <span>{Math.round(topHypothesis.confidence * 100)}%</span>
                  )}
                </div>
                <p>
                  {topHypothesis?.summary ??
                    "The selected cohort is too small to form a defensible hypothesis."}
                </p>
                <button
                  className="investigate-button"
                  type="button"
                  onClick={() => topHypothesis && setDrawerOpen(true)}
                  disabled={!topHypothesis}
                >
                  {topHypothesis ? "Investigate signal" : "Not enough evidence"}
                  {topHypothesis && <ArrowRight size={17} weight="bold" />}
                </button>
              </section>

              <section className="evidence-breakdown">
                <BreakdownGroup
                  title="Products"
                  items={data.affectedProducts.map((product) => ({
                    id: product.id,
                    label: product.shortName,
                    value: `${product.current.complaints}/${product.current.reviews}`,
                    icon: Package,
                  }))}
                />
                <BreakdownGroup
                  title="Channels"
                  items={data.sourceCounts
                    .filter((item) => item.count > 0)
                    .map((item) => ({
                      id: item.source,
                      label: item.label,
                      value: String(item.count),
                      icon: SOURCE_ICONS[item.source],
                    }))}
                />
                <BreakdownGroup
                  title="Issue themes"
                  items={data.themes.slice(0, 4).map((theme) => ({
                    id: theme.label,
                    label: theme.label,
                    value: String(theme.count),
                    icon: WarningCircle,
                  }))}
                  tone="critical"
                />
                <BreakdownGroup
                  title="Evidence sources"
                  items={[
                    { id: "reviews", label: "Matching complaints", value: String(data.currentComplaints), icon: Chats },
                    { id: "hypotheses", label: "Shown hypotheses", value: String(data.hypotheses.length), icon: SquaresFour },
                    { id: "products", label: "Products in scope", value: String(data.selectedProducts.length), icon: Cube },
                  ]}
                  tone="evidence"
                />
              </section>

              <section className="active-actions">
                <div className="section-heading section-heading--compact">
                  <div>
                    <span className="eyebrow">Workflow</span>
                    <h3>Active actions</h3>
                  </div>
                  <span>{visibleActions.length + (hasSeededAlert ? 1 : 0)}</span>
                </div>
                <div className="action-list">
                  {hasSeededAlert && (
                    <article className="action-row">
                      <span className="action-row__icon action-row__icon--alert"><Alarm size={18} /></span>
                      <span>
                        <strong>Alert: packaging complaints spike</strong>
                        <small>{data.scopeLabel} · Detected 08:15</small>
                      </span>
                      <em>Open</em>
                    </article>
                  )}
                  {visibleActions.slice(0, 2).map((action) => (
                    <article className="action-row" key={action.id}>
                      <span className="action-row__icon action-row__icon--success"><CheckCircle size={18} /></span>
                      <span>
                        <strong>Audit packaging and seal process</strong>
                        <small>{action.owner} · Due {action.dueDate}</small>
                      </span>
                      <em>{action.status}</em>
                    </article>
                  ))}
                  {!hasSeededAlert && visibleActions.length === 0 && (
                    <div className="action-list__empty">
                      No active actions for this product cohort.
                    </div>
                  )}
                </div>
              </section>
            </>
          ) : (
            <div className="evidence-empty">
              <Package size={28} aria-hidden="true" />
              <h3>No product cohort</h3>
              <p>Select at least one product to build evidence and compare customer feedback.</p>
            </div>
          )}
        </aside>
          </div>
        </details>
      </main>

      {drawerOpen && data.selectedProducts.length > 0 && (
        <InvestigationDrawer
          data={data}
          onClose={() => setDrawerOpen(false)}
          onCreateAction={createAction}
        />
      )}
    </div>
  );
}

type MetricProps = {
  value: string;
  label: string;
  detail: string;
  tone?: "critical" | "positive";
};

function Metric({ value, label, detail, tone }: MetricProps) {
  return (
    <div className={`metric ${tone ? `metric--${tone}` : ""}`}>
      <strong>{value}</strong>
      <span>{label}</span>
      <small>{detail}</small>
    </div>
  );
}

type BreakdownItem = {
  id: string;
  label: string;
  value: string;
  icon: typeof Package;
};

function BreakdownGroup({
  title,
  items,
  tone = "default",
}: {
  title: string;
  items: BreakdownItem[];
  tone?: "default" | "critical" | "evidence";
}) {
  return (
    <div className={`breakdown-group breakdown-group--${tone}`}>
      <span className="breakdown-group__title">{title}</span>
      <div className="breakdown-group__items">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <div className="breakdown-item" key={item.id}>
              <span className="breakdown-item__icon"><Icon size={16} /></span>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EmptyCohort({ onShowAll }: { onShowAll: () => void }) {
  return (
    <section className="empty-cohort">
      <div className="empty-cohort__icon"><Package size={30} /></div>
      <span className="eyebrow">Product filter</span>
      <h2>Select products to build a comparable customer-feedback cohort.</h2>
      <p>
        Metrics, signal activity, evidence, hypotheses and competitor context all use the same selected products.
      </p>
      <button className="primary-button" type="button" onClick={onShowAll}>
        Show all products <ArrowRight size={17} weight="bold" />
      </button>
    </section>
  );
}
