import {
  ArrowRight,
  ChatCircleText,
  CheckCircle,
  Clock,
  Database,
  Info,
  Package,
  Pulse,
  Storefront,
  TrendDown,
  TrendUp,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import type { DashboardData, DashboardProduct } from "../api/types";
import { ProductFilter } from "./ProductFilter";

interface DashboardProps {
  data: DashboardData;
}

function productName(product: DashboardProduct): string {
  return product.shortName ?? product.name ?? `Unidentified product · ${product.id}`;
}

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}

function percent(value: number | null, digits = 1): string {
  return value === null
    ? "Not available"
    : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: digits }).format(value);
}

function dateLabel(
  value: string | null,
  options: { exclusiveEnd?: boolean; timeZone?: string | null } = {},
): string {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  const displayDate = options.exclusiveEnd ? new Date(date.getTime() - 1) : date;
  const formatOptions: Intl.DateTimeFormatOptions = {
    day: "2-digit",
    month: "short",
    year: "numeric",
  };
  if (options.timeZone) formatOptions.timeZone = options.timeZone;
  try {
    return new Intl.DateTimeFormat("en-GB", formatOptions).format(displayDate);
  } catch {
    delete formatOptions.timeZone;
    return new Intl.DateTimeFormat("en-GB", formatOptions).format(displayDate);
  }
}

function sourceLabel(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function insightLabel(value: string): string {
  return `${sourceLabel(value)} decision`;
}

function complaintChange(product: DashboardProduct): number | null {
  const current = ratio(product.current.complaints, product.current.feedback);
  const baseline = ratio(product.baseline.complaints, product.baseline.feedback);
  return current === null || baseline === null ? null : (current - baseline) * 100;
}

function productMetadata(product: DashboardProduct): string {
  if (product.id === "unattributed") {
    return "Unattributed feedback bucket · no product metadata supplied";
  }
  const details = [product.sku, product.category, product.pack].filter(Boolean);
  return details.length ? details.join(" · ") : `Catalog metadata unavailable · ${product.id}`;
}

export function Dashboard({ data }: DashboardProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => data.products.map((product) => product.id));

  useEffect(() => {
    setSelectedIds(data.products.map((product) => product.id));
  }, [data]);

  const selectedProducts = useMemo(
    () => data.products.filter((product) => selectedIds.includes(product.id)),
    [data.products, selectedIds],
  );
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedEvidence = data.evidence.filter((item) =>
    item.productId === null || selectedSet.has(item.productId),
  );
  const totals = selectedProducts.reduce((result, product) => ({
    feedback: result.feedback + product.current.feedback,
    complaints: result.complaints + product.current.complaints,
    positive: result.positive + product.current.positive,
    neutral: result.neutral + product.current.neutral,
  }), { feedback: 0, complaints: 0, positive: 0, neutral: 0 });
  const sources = useMemo(() => {
    const counts = new Map<string, number>();
    selectedProducts.forEach((product) => product.sources.forEach((source) => {
      counts.set(source.sourceGroup, (counts.get(source.sourceGroup) ?? 0) + source.count);
    }));
    return [...counts.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count);
  }, [selectedProducts]);
  const themes = useMemo(() => {
    const counts = new Map<string, number>();
    selectedProducts.forEach((product) => product.themes.forEach((theme) => {
      counts.set(theme.label, (counts.get(theme.label) ?? 0) + theme.count);
    }));
    return [...counts.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count);
  }, [selectedProducts]);
  const incompleteMetadata = selectedProducts.filter((product) => !product.metadataComplete);
  const analysisCoverage = ratio(data.coverage.analyzedItems, data.coverage.feedbackItems);

  return (
    <>
      {data.dataState === "partial" && (
        <section className="truth-banner truth-banner--partial" role="status">
          <WarningCircle size={21} weight="fill" />
          <div>
            <strong>Partial dashboard</strong>
            <p>{data.messages[0] ?? "The backend returned usable data with incomplete coverage."}</p>
          </div>
        </section>
      )}

      <section className="portfolio-toolbar" aria-label="Product portfolio scope">
        <div>
          <span className="eyebrow">Current API view</span>
          <strong>Guardian customer feedback portfolio</strong>
          <small>{dateLabel(data.windows.currentStart, { timeZone: data.windows.businessTimezone })} — {dateLabel(data.windows.currentEnd, { exclusiveEnd: true, timeZone: data.windows.businessTimezone })}{data.windows.businessTimezone ? ` · ${data.windows.businessTimezone}` : ""}</small>
        </div>
        <ProductFilter products={data.products} selectedIds={selectedIds} onChange={setSelectedIds} />
      </section>

      {selectedProducts.length === 0 ? (
        <section className="empty-cohort">
          <span className="empty-cohort__icon"><Package size={28} /></span>
          <h2>No products selected</h2>
          <p>Select one or more products from the API-backed product filter to view their feedback.</p>
          <button className="primary-button" type="button" onClick={() => setSelectedIds(data.products.map((product) => product.id))}>Show all products</button>
        </section>
      ) : (
        <div className="portfolio-overview">
          <section className="portfolio-health" aria-labelledby="portfolio-health-title">
            <div className="portfolio-health__head">
              <div>
                <span className="eyebrow">Portfolio feedback · current server window</span>
                <h2 id="portfolio-health-title">What customers reported across selected products</h2>
                <p>{totals.feedback.toLocaleString()} server-grouped feedback items across {selectedProducts.length} product groups, including any unattributed bucket.</p>
              </div>
              <span className={`server-state server-state--${data.dataState}`}><Database size={14} /> {data.dataState} data</span>
            </div>
            <div className="sentiment-summary" aria-label="Server-reported portfolio counts">
              <div className="sentiment-summary__total"><ChatCircleText size={20} /><strong>{totals.feedback.toLocaleString()}</strong><span>feedback in window</span></div>
              <div className="sentiment-stat sentiment-stat--positive"><strong>{totals.positive.toLocaleString()}</strong><span>Positive</span><small>server classified</small></div>
              <div className="sentiment-stat sentiment-stat--neutral"><strong>{totals.neutral.toLocaleString()}</strong><span>Neutral</span><small>server classified</small></div>
              <div className="sentiment-stat sentiment-stat--negative"><strong>{totals.complaints.toLocaleString()}</strong><span>Complaints</span><small>{percent(ratio(totals.complaints, totals.feedback))} of feedback</small></div>
            </div>
            <p className="sentiment-method">Counts come directly from <code>/api/v1/dashboard</code>. Complaints and sentiment labels are displayed as separate backend measures and are not forced into a synthetic distribution.</p>
          </section>

          <section className="coverage-strip" aria-label="Dashboard data coverage">
            <div><span>All feedback</span><strong>{data.coverage.feedbackItems.toLocaleString()}</strong></div>
            <div><span>Analyzed</span><strong>{data.coverage.analyzedItems.toLocaleString()}</strong><small>{percent(analysisCoverage)} coverage</small></div>
            <div><span>Relevant</span><strong>{data.coverage.relevantItems.toLocaleString()}</strong></div>
            <div><span>Time eligible</span><strong>{data.coverage.timeEligibleItems.toLocaleString()}</strong></div>
            <div><span>Product attributed</span><strong>{data.coverage.productAttributedItems.toLocaleString()}</strong></div>
          </section>

          {incompleteMetadata.length > 0 && (
            <section className="metadata-notice" role="note">
              <Info size={20} weight="fill" />
              <div>
                <strong>Product catalog details are incomplete</strong>
                <p>{incompleteMetadata.length} selected {incompleteMetadata.length === 1 ? "product has" : "products have"} only the metadata supplied by ingestion. Missing names, SKUs, categories, packs, or ratings are shown as unavailable; no catalog values are guessed.</p>
              </div>
            </section>
          )}

          {data.primaryInsight && (
            <section className="primary-insight" aria-labelledby="primary-insight-title">
              <div className="primary-insight__icon"><Pulse size={25} weight="fill" /></div>
              <div>
                <span className="eyebrow">Primary server insight</span>
                <div className="primary-insight__labels">
                  {data.primaryInsight.label && <span className={`decision-label decision-label--${data.primaryInsight.label}`}>{insightLabel(data.primaryInsight.label)}</span>}
                  {data.primaryInsight.status && <span className="workflow-status">Workflow: {sourceLabel(data.primaryInsight.status)}</span>}
                </div>
                <h2 id="primary-insight-title">{data.primaryInsight.title}</h2>
                {data.primaryInsight.summary && <p>{data.primaryInsight.summary}</p>}
                <div className="primary-insight__metrics">
                  {data.primaryInsight.currentShare !== null && <span><strong>{percent(data.primaryInsight.currentShare)}</strong> current share</span>}
                  {data.primaryInsight.baselineShare !== null && <span><strong>{percent(data.primaryInsight.baselineShare)}</strong> baseline</span>}
                  {data.primaryInsight.confidenceLevel && <span><strong>{data.primaryInsight.confidenceLevel}</strong> confidence</span>}
                </div>
                {data.primaryInsight.recommendedActions.length > 0 && (
                  <ul>{data.primaryInsight.recommendedActions.map((action) => <li key={action}>{action}</li>)}</ul>
                )}
              </div>
            </section>
          )}

          <div className="portfolio-overview__grid">
            <section className="portfolio-table-section">
              <div className="portfolio-section-head">
                <div><span className="eyebrow">API product groups</span><h3>Feedback by product</h3></div>
                <span>Current window vs baseline</span>
              </div>
              <div className="portfolio-table" role="table" aria-label="Feedback by product">
                <div className="portfolio-table__head" role="row">
                  <span>Product</span><span>Feedback</span><span>Complaint rate</span><span>Change</span><span>Top theme</span><span aria-hidden="true" />
                </div>
                {selectedProducts.map((product) => {
                  const change = complaintChange(product);
                  const complaintRate = ratio(product.current.complaints, product.current.feedback);
                  return (
                    <div className="portfolio-table__row" role="row" key={product.id}>
                      <button type="button" className="portfolio-product" onClick={() => setSelectedIds([product.id])}>
                        <strong>{productName(product)}</strong><small>{productMetadata(product)}</small>
                      </button>
                      <span className="portfolio-count"><strong>{product.current.feedback.toLocaleString()}</strong><small>baseline {product.baseline.feedback.toLocaleString()}</small></span>
                      <strong className="portfolio-negative">{percent(complaintRate)}</strong>
                      <span className={`portfolio-trend ${change !== null && change <= 0 ? "is-up" : "is-down"}`}>
                        {change === null ? <Clock size={16} /> : change <= 0 ? <TrendDown size={16} /> : <TrendUp size={16} />}
                        {change === null ? "No baseline" : `${change > 0 ? "+" : ""}${change.toFixed(1)}pp`}
                      </span>
                      <span className="portfolio-top-problem"><strong>{product.themes[0]?.label ?? "No theme reported"}</strong><small>{product.themes[0] ? `${product.themes[0].count.toLocaleString()} mentions` : "Insufficient topic data"}</small></span>
                      <button type="button" className="portfolio-investigate" onClick={() => setSelectedIds([product.id])} aria-label={`Focus ${productName(product)}`}>
                        View evidence <ArrowRight size={14} weight="bold" />
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>

            <aside className="portfolio-side">
              <section className="theme-summary">
                <div className="portfolio-section-head"><div><span className="eyebrow">Reported topics</span><h3>Top themes</h3></div></div>
                {themes.length > 0 ? (
                  <div className="theme-list">{themes.slice(0, 6).map((theme, index) => (
                    <div key={theme.label}><span><i>{String(index + 1).padStart(2, "0")}</i>{theme.label}</span><strong>{theme.count.toLocaleString()}</strong></div>
                  ))}</div>
                ) : <p className="insufficient-copy">The API did not return theme counts for this selection.</p>}
              </section>
              <section className="source-summary">
                <div className="portfolio-section-head"><div><span className="eyebrow">Coverage</span><h3>Source groups</h3></div></div>
                {sources.length > 0 ? <div className="source-bars">{sources.map((source) => (
                  <div key={source.label}><span>{sourceLabel(source.label)}</span><strong>{source.count.toLocaleString()}</strong></div>
                ))}</div> : <p className="insufficient-copy">No per-product source breakdown is available.</p>}
              </section>
            </aside>
          </div>

          <div className="evidence-benchmark-grid">
            <section className="evidence-panel">
              <div className="portfolio-section-head">
                <div><span className="eyebrow">Customer evidence</span><h3>Reported excerpts</h3></div>
                <span>{selectedEvidence.length} returned</span>
              </div>
              {selectedEvidence.length > 0 ? <div className="evidence-list">{selectedEvidence.slice(0, 6).map((item) => (
                <blockquote key={item.id}>
                  <p>“{item.text}”</p>
                  <footer>
                    <span>{item.sourcePlatform} · {sourceLabel(item.sourceGroup)}</span>
                    <span>{item.timestamp ? dateLabel(item.timestamp) : "Date unavailable"}{item.confidence !== null ? ` · ${percent(item.confidence, 0)} match` : ""}</span>
                  </footer>
                </blockquote>
              ))}</div> : <p className="insufficient-copy">No redacted evidence excerpts were returned for this product scope.</p>}
            </section>

            <section className="benchmark-panel">
              <div className="portfolio-section-head"><div><span className="eyebrow">Portfolio-wide peer context</span><h3>Global comparable benchmark</h3></div></div>
              <p className="benchmark-scope-note">This backend benchmark covers the complete matched portfolio cohort and does not recalculate with the product filter{selectedProducts.length !== data.products.length ? "; the current product selection is narrower" : ""}.</p>
              {!data.benchmark || !data.benchmark.comparable ? (
                <div className="benchmark-unavailable"><Storefront size={24} /><strong>Comparison not available</strong><p>{data.benchmark?.reason ?? "The backend did not return a comparable competitor cohort."}</p></div>
              ) : data.benchmark.brands.length > 0 ? (
                <div className="benchmark-list">{data.benchmark.brands.map((brand) => (
                  <div key={brand.brand}><span>{sourceLabel(brand.brand)}</span><strong>{percent(brand.share)}</strong><small>{brand.complaints?.toLocaleString() ?? "—"} complaints / {brand.feedback?.toLocaleString() ?? "—"} feedback{brand.rating !== null ? ` · ${brand.rating.toFixed(1)} rating (${brand.ratingCount?.toLocaleString() ?? 0})` : ""}{brand.positive !== null && brand.neutral !== null ? ` · ${brand.positive.toLocaleString()} positive · ${brand.neutral.toLocaleString()} neutral` : ""}</small></div>
                ))}</div>
              ) : <p className="insufficient-copy">The cohort is marked comparable, but no brand aggregates were returned.</p>}
            </section>
          </div>

          {data.messages.length > (data.dataState === "partial" ? 1 : 0) && (
            <section className="server-notes">
              <CheckCircle size={19} /><div><strong>Backend data notes</strong><ul>{data.messages.slice(data.dataState === "partial" ? 1 : 0).map((message) => <li key={message}>{message}</li>)}</ul></div>
            </section>
          )}
        </div>
      )}
    </>
  );
}
