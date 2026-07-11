import { useMemo, useState } from "react";
import {
  ChartBar,
  Package,
  ShieldWarning,
  TrendUp,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  PRODUCTS,
  FEEDBACK_WINDOWS,
  FEEDBACK_WINDOW_LABELS,
  SOURCE_LABELS,
  deriveDashboard,
  formatPercent,
  formatVelocity,
  type ProductId,
  type FeedbackWindow,
} from "../data/dashboard";
import { DashboardCharts } from "./DashboardCharts";
import { ProductProblems } from "./ProductProblems";
import { TimeRangeSelect } from "./TimeRangeSelect";

type DashboardData = ReturnType<typeof deriveDashboard>;
const SHOW_SUPPORTING_SECTIONS = false; // Temporarily hidden; keep the implementation ready to restore.

function productRate(product: DashboardData["selectedProducts"][number]) {
  return product.current.reviews ? (product.current.complaints / product.current.reviews) * 100 : 0;
}

function baselineRate(product: DashboardData["selectedProducts"][number]) {
  return product.baseline.reviews ? (product.baseline.complaints / product.baseline.reviews) * 100 : 0;
}

function ComparisonBars({
  label,
  current,
  previous,
  formatValue,
  formatDelta = formatValue,
}: {
  label: string;
  current: number;
  previous: number;
  formatValue: (value: number) => string;
  formatDelta?: (value: number) => string;
}) {
  const maximum = Math.max(current, previous, 1);
  const delta = current - previous;
  return (
    <div className="comparison-bars">
      <div className="comparison-bars__head">
        <strong>{label}</strong>
        <span className={delta > 0 ? "is-up" : delta < 0 ? "is-down" : ""}>
          {delta > 0 ? "+" : ""}{formatDelta(delta)}
        </span>
      </div>
      <div className="comparison-bar-row">
        <span>Current</span><i><b style={{ width: `${(current / maximum) * 100}%` }} /></i><strong>{formatValue(current)}</strong>
      </div>
      <div className="comparison-bar-row is-previous">
        <span>Previous</span><i><b style={{ width: `${(previous / maximum) * 100}%` }} /></i><strong>{formatValue(previous)}</strong>
      </div>
    </div>
  );
}

export function FocusedDashboard({
  data,
  onSelectProduct,
}: {
  data: DashboardData;
  onSelectProduct: (id: ProductId) => void;
}) {
  const [incidentWindow, setIncidentWindow] = useState<FeedbackWindow>("72h");
  const [compareMode, setCompareMode] = useState(false);
  const driverProducts = useMemo(() => {
    if (data.selectedProducts.length <= 1) return data.selectedProducts;
    const clearDrivers = data.affectedProducts.filter((product) => {
      const baseline = baselineRate(product);
      return product.current.complaints >= 5 && baseline > 0 && productRate(product) / baseline >= 2;
    });
    return clearDrivers.length ? clearDrivers : data.affectedProducts.slice(0, 2);
  }, [data.affectedProducts, data.selectedProducts]);

  const incident = useMemo(
    () => deriveDashboard(driverProducts.map((product) => product.id), incidentWindow),
    [driverProducts, incidentWindow],
  );
  const previousIncident = useMemo(
    () => deriveDashboard(driverProducts.map((product) => product.id), incidentWindow, "previous"),
    [driverProducts, incidentWindow],
  );
  const incidentProducts = incident.selectedProducts;
  const topHypothesis = incident.hypotheses[0];
  const recommendedAction = incident.recommendedAction;
  const confirmingChannelCount = incident.sourceCounts.filter((source) => source.count > 0).length;
  const topProblems = incident.themes.slice(0, 3).map((problem, index) => ({
    ...problem,
    severity: index === 0 ? "Critical" : index === 1 ? "High" : "Moderate",
  }));
  const problemNames = topProblems.map((problem) => {
    if (problem.label === "Leaking") return "leakage";
    if (problem.label === "Broken cap") return "broken caps";
    return problem.label.toLowerCase();
  });
  const problemSummary = problemNames.length === 1
    ? problemNames[0]
    : `${problemNames.slice(0, -1).join(", ")}, and ${problemNames.at(-1)}`;
  const coreInsightTitle = problemNames.length
    ? `Users are complaining about ${problemSummary}.`
    : "Not enough evidence to summarize the main customer problems.";
  const supportingEvidence = incident.evidence.filter((item) => item.stance === "support");
  const categoryLabel = new Set(incidentProducts.map((product) => product.category)).size === 1
    ? incidentProducts[0]?.category.toLowerCase()
    : "affected";
  const otherProducts = data.selectedProducts.filter(
    (product) => !driverProducts.some((driver) => driver.id === product.id),
  );

  return (
    <div className="focused-dashboard">
      <div className="product-decision-header">
        <section className="incident-hero" aria-labelledby="incident-title">
          <div className="incident-hero__topline">
            <span className={`incident-severity incident-severity--${incident.status ?? "watch"}`}>
              <ShieldWarning size={16} weight="fill" /> {incident.status === "critical" ? "Critical incident" : "Needs attention"}
            </span>
            <div className="incident-window-controls">
              <TimeRangeSelect
                ariaLabel="Filter incident by time"
                value={incidentWindow}
                options={FEEDBACK_WINDOWS.map((value) => ({ value, label: FEEDBACK_WINDOW_LABELS[value] }))}
                onChange={setIncidentWindow}
              />
              <button
                type="button"
                className={`comparison-toggle${compareMode ? " is-active" : ""}`}
                role="switch"
                aria-checked={compareMode}
                onClick={() => setCompareMode((current) => !current)}
              >
                <span aria-hidden="true"><i /></span>
                Compare periods
              </button>
              <span className="incident-freshness">Synthetic demo</span>
            </div>
          </div>

          <div className="incident-hero__title">
            <div>
              <span className="eyebrow">Customer issue · {categoryLabel}</span>
              <h2 id="incident-title">{coreInsightTitle}</h2>
              <p>{incidentProducts.map((product) => product.name).join(" · ")}</p>
            </div>
          </div>

          <div className="incident-metrics" aria-label="Incident severity summary">
            <div>
              <strong>{incident.currentComplaints}/{incident.currentReviews}</strong>
              <span>complaints / reviews</span>
              <small>in the affected cohort</small>
            </div>
            <div>
              <strong>{formatPercent(incident.complaintShare)}</strong>
              <span>complaint rate</span>
              <small>{FEEDBACK_WINDOW_LABELS[incidentWindow].toLowerCase()}</small>
            </div>
            <div>
              <strong>{driverProducts.length}</strong>
              <span>affected SKUs</span>
              <small>products driving the issue</small>
            </div>
            <div>
              <strong>{confirmingChannelCount}</strong>
              <span>feedback channels</span>
              <small>independent customer sources</small>
            </div>
          </div>

          {compareMode && (
            <div className="incident-comparison" role="img" aria-label={`${FEEDBACK_WINDOW_LABELS[incidentWindow]} compared with the previous matching period`}>
              <div className="incident-comparison__head">
                <div><span className="step-label">Period comparison</span><h3>Current vs previous period</h3></div>
                <span>Same-length periods</span>
              </div>
              <div className="incident-comparison__grid">
                <ComparisonBars
                  label="Complaint rate"
                  current={incident.complaintShare ?? 0}
                  previous={previousIncident.complaintShare ?? 0}
                  formatValue={(value) => `${value.toFixed(1)}%`}
                  formatDelta={(value) => `${value.toFixed(1)}pp`}
                />
                <ComparisonBars
                  label="Complaint mentions"
                  current={incident.currentComplaints}
                  previous={previousIncident.currentComplaints}
                  formatValue={(value) => String(Math.round(value))}
                />
              </div>
            </div>
          )}

          <div className="incident-core-insight">
            <div className="incident-core-insight__head">
              <div><span className="step-label">AI-generated core insight</span><h3>Top 3 customer problems</h3></div>
              {topHypothesis && <span className="confidence-score">AI · {Math.round(topHypothesis.confidence * 100)}% confidence</span>}
            </div>
            <ul className="core-problem-list">
              {topProblems.map((problem) => (
                <li key={problem.label}>
                  <span className={`problem-severity problem-severity--${problem.severity.toLowerCase()}`}>{problem.severity}</span>
                  <strong>{problem.label}</strong>
                  <small>{problem.count} customer mentions</small>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="focus-card action-card action-card--header">
          <div className="focus-card__head">
            <div><span className="step-label">Recommended corrective action</span><h3>What to do next</h3></div>
            <span className={`action-priority action-priority--${recommendedAction?.priority.toLowerCase() ?? "medium"}`}>
              {recommendedAction?.priority ?? "Needs evidence"}
            </span>
          </div>
          <ul className="action-recommendation-list">
            {(recommendedAction?.steps ?? ["Collect more independent evidence before assigning a corrective action."]).map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </section>
      </div>

      {data.selectedProducts.length !== driverProducts.length && (
        <div className="scope-explainer" role="note">
          <WarningCircle size={18} weight="fill" />
          <span>
            <strong>Why only {driverProducts.length} products?</strong>
            The portfolio filter includes {data.selectedProducts.length}, but these {driverProducts.length} SKUs drive the active spike. Other products remain available under More context.
          </span>
        </div>
      )}

      {data.selectedProducts.length === 1 && <ProductProblems product={data.selectedProducts[0]} compareMode={compareMode} />}

      {SHOW_SUPPORTING_SECTIONS && (
        <>
      <div className="incident-grid">
        <section className="focus-card">
          <div className="focus-card__head">
            <div><span className="step-label">03 · Scope</span><h3>Products driving the issue</h3></div>
            <span>{driverProducts.length} affected SKUs</span>
          </div>
          <div className="driver-products">
            {driverProducts.map((product) => {
              const rate = productRate(product);
              const baseline = baselineRate(product);
              return (
                <button type="button" key={product.id} onClick={() => onSelectProduct(product.id)}>
                  <span className="driver-product__icon"><Package size={20} /></span>
                  <span className="driver-product__name">
                    <strong>{product.name}</strong>
                    <small>{product.sku} · {product.pack}</small>
                  </span>
                  <span className="driver-product__rate">
                    <strong>{rate.toFixed(1)}%</strong>
                    <small>{product.current.complaints}/{product.current.reviews} · baseline {baseline.toFixed(1)}%</small>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="focus-card">
          <div className="focus-card__head">
            <div><span className="step-label">04 · Independent support</span><h3>Channels confirming the issue</h3></div>
            <span>mention count</span>
          </div>
          <div className="channel-summary">
            {incident.sourceCounts.filter((source) => source.count > 0).map((source) => (
              <div key={source.source}>
                <span>{source.label}</span><strong>{source.count}</strong>
              </div>
            ))}
          </div>
          <p className="data-caveat">Counts are supporting mentions, not normalized channel rates.</p>
        </section>
      </div>

      <section className="focus-card evidence-brief">
        <div className="focus-card__head">
          <div><span className="step-label">05 · Customer evidence</span><h3>What customers actually reported</h3></div>
          <span>{supportingEvidence.length} representative samples</span>
        </div>
        <div className="evidence-brief__quotes">
          {supportingEvidence.slice(0, 3).map((item) => {
            const product = PRODUCTS.find((product) => product.id === item.productId);
            return (
              <blockquote key={item.id}>
                <p>“{item.quote}”</p>
                <footer>{product?.shortName} · {SOURCE_LABELS[item.source]} · {Math.round(item.confidence * 100)}% match</footer>
              </blockquote>
            );
          })}
        </div>
      </section>

      <details className="more-context">
        <summary><span><ChartBar size={18} /> Supporting analysis</span><small>Product ranking, issue mix, channels and peer context</small></summary>
        <div className="more-context__grid">
          <section>
            <h3>Other selected products</h3>
            {otherProducts.length ? otherProducts.map((product) => (
              <div className="context-row" key={product.id}>
                <span>{product.shortName}</span><strong>{productRate(product).toFixed(1)}%</strong>
              </div>
            )) : <p>No additional products in the selected scope.</p>}
          </section>
          <section>
            <h3>Synthetic peer comparison</h3>
            <div className="context-row"><span>Guardian affected cohort</span><strong>{formatPercent(incident.complaintShare)}</strong></div>
            {incident.competitors.map((competitor) => (
              <div className="context-row" key={competitor.retailer}>
                <span>{competitor.retailer === "hasaki" ? "Hasaki" : "Watsons"} · {competitor.complaints}/{competitor.reviews}</span>
                <strong>{formatPercent(competitor.share)}</strong>
              </div>
            ))}
            <p className="data-caveat">Demo fixture only; no production cohort-matching method is connected.</p>
          </section>
        </div>
        <DashboardCharts
          data={data}
          signalLabel={`${formatVelocity(incident.velocity)} above baseline in ${driverProducts.length} affected SKU${driverProducts.length === 1 ? "" : "s"}`}
        />
      </details>
        </>
      )}
    </div>
  );
}
