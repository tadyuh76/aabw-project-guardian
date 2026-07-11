import { useMemo } from "react";
import {
  ArrowRight,
  ChartBar,
  CheckCircle,
  Clock,
  Package,
  ShieldWarning,
  Storefront,
  TrendUp,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  PRODUCTS,
  SOURCE_LABELS,
  deriveDashboard,
  formatPercent,
  formatVelocity,
  type ProductId,
} from "../data/dashboard";
import { DashboardCharts } from "./DashboardCharts";
import { ProductProblems } from "./ProductProblems";

type DashboardData = ReturnType<typeof deriveDashboard>;

function productRate(product: DashboardData["selectedProducts"][number]) {
  return product.current.reviews ? (product.current.complaints / product.current.reviews) * 100 : 0;
}

function baselineRate(product: DashboardData["selectedProducts"][number]) {
  return product.baseline.reviews ? (product.baseline.complaints / product.baseline.reviews) * 100 : 0;
}

export function FocusedDashboard({
  data,
  onInvestigate,
  onSelectProduct,
}: {
  data: DashboardData;
  onInvestigate: (ids: ProductId[]) => void;
  onSelectProduct: (id: ProductId) => void;
}) {
  const driverProducts = useMemo(() => {
    if (data.selectedProducts.length <= 1) return data.selectedProducts;
    const clearDrivers = data.affectedProducts.filter((product) => {
      const baseline = baselineRate(product);
      return product.current.complaints >= 5 && baseline > 0 && productRate(product) / baseline >= 2;
    });
    return clearDrivers.length ? clearDrivers : data.affectedProducts.slice(0, 2);
  }, [data.affectedProducts, data.selectedProducts]);

  const incident = useMemo(
    () => deriveDashboard(driverProducts.map((product) => product.id)),
    [driverProducts],
  );
  const topTheme = incident.themes[0]?.label ?? "Packaging";
  const topHypothesis = incident.hypotheses[0];
  const supportingEvidence = incident.evidence.filter((item) => item.stance === "support");
  const categoryLabel = new Set(driverProducts.map((product) => product.category)).size === 1
    ? driverProducts[0]?.category.toLowerCase()
    : "affected";
  const headline = driverProducts.length === 1
    ? `${topTheme} complaints detected in ${driverProducts[0].shortName}`
    : `${topTheme} complaints spiked across ${driverProducts.length} ${categoryLabel} products`;
  const otherProducts = data.selectedProducts.filter(
    (product) => !driverProducts.some((driver) => driver.id === product.id),
  );

  return (
    <div className="focused-dashboard">
      <section className="incident-hero" aria-labelledby="incident-title">
        <div className="incident-hero__topline">
          <span className={`incident-severity incident-severity--${incident.status ?? "watch"}`}>
            <ShieldWarning size={16} weight="fill" /> {incident.status === "critical" ? "Critical incident" : "Needs attention"}
          </span>
          <span className="incident-freshness"><Clock size={15} /> Last 72 hours · Synthetic demo</span>
        </div>

        <div className="incident-hero__title">
          <div>
            <span className="eyebrow">Customer issue · {categoryLabel}</span>
            <h2 id="incident-title">{headline}</h2>
            <p>{driverProducts.map((product) => product.name).join(" · ")}</p>
          </div>
          <button type="button" onClick={() => onInvestigate(driverProducts.map((product) => product.id))} disabled={!topHypothesis}>
            Investigate this incident <ArrowRight size={17} weight="bold" />
          </button>
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
            <small>current 72-hour window</small>
          </div>
          <div>
            <strong>{formatPercent(incident.baselineShare)}</strong>
            <span>28-day baseline</span>
            <small>same affected products</small>
          </div>
          <div>
            <strong>{formatVelocity(incident.velocity)}</strong>
            <span>above baseline</span>
            <small>rate comparison</small>
          </div>
        </div>
      </section>

      {data.selectedProducts.length !== driverProducts.length && (
        <div className="scope-explainer" role="note">
          <WarningCircle size={18} weight="fill" />
          <span>
            <strong>Why only {driverProducts.length} products?</strong>
            The portfolio filter includes {data.selectedProducts.length}, but these {driverProducts.length} SKUs drive the active spike. Other products remain available under More context.
          </span>
        </div>
      )}

      {data.selectedProducts.length === 1 && <ProductProblems product={data.selectedProducts[0]} />}

      <div className="incident-grid">
        <section className="focus-card">
          <div className="focus-card__head">
            <div><span className="step-label">01 · Scope</span><h3>Products driving the issue</h3></div>
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
            <div><span className="step-label">02 · Independent support</span><h3>Channels confirming the issue</h3></div>
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
          <div><span className="step-label">03 · Customer evidence</span><h3>What customers actually reported</h3></div>
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

      <div className="decision-grid">
        <section className="focus-card hypothesis-card">
          <div className="focus-card__head">
            <div><span className="step-label">04 · Likely cause</span><h3>{topHypothesis?.title ?? "Not enough evidence"}</h3></div>
            {topHypothesis && <span className="confidence-score">{Math.round(topHypothesis.confidence * 100)}% model score</span>}
          </div>
          <p>{topHypothesis?.summary ?? "More independent evidence is required before forming a hypothesis."}</p>
          {topHypothesis && (
            <div className="evidence-balance">
              <span><CheckCircle size={17} /> <strong>{topHypothesis.support}</strong> supporting</span>
              <span><WarningCircle size={17} /> <strong>{topHypothesis.contradict}</strong> contradicting</span>
            </div>
          )}
          <small className="data-caveat">Score combines evidence balance, complaint coverage and channel breadth.</small>
        </section>

        <section className="focus-card action-card">
          <div className="focus-card__head">
            <div><span className="step-label">05 · Decision</span><h3>What to do next</h3></div>
            <span>Suggested today</span>
          </div>
          <div className="action-card__body">
            <span className="action-card__icon"><Storefront size={22} weight="fill" /></span>
            <div>
              <strong>Audit pump-neck seal and protective wrap</strong>
              <p>Owner: E-commerce Operations · Recheck complaint rate after 48 hours.</p>
            </div>
          </div>
          <button type="button" onClick={() => onInvestigate(driverProducts.map((product) => product.id))} disabled={!topHypothesis}>
            Open evidence and assign <ArrowRight size={16} weight="bold" />
          </button>
        </section>
      </div>

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
    </div>
  );
}
