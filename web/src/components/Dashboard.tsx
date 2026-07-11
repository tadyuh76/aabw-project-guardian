import {
  ArrowRight,
  ChatCircleDots,
  Database,
  Drop,
  Info,
  Package,
  Pulse,
  Star,
  TrendDown,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import type { DashboardData, DashboardProduct, ProductTheme } from "../api/types";
import { ProductFilter } from "./ProductFilter";

interface DashboardProps { data: DashboardData; }

function productName(product: DashboardProduct): string {
  return product.shortName ?? product.name ?? `Unidentified product · ${product.id}`;
}

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}

function percent(value: number | null, digits = 1): string {
  return value === null ? "—" : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: digits }).format(value);
}

function dateLabel(value: string | null, options: { exclusiveEnd?: boolean; timeZone?: string | null } = {}): string {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  const displayDate = options.exclusiveEnd ? new Date(date.getTime() - 1) : date;
  try {
    return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: options.timeZone ?? undefined }).format(displayDate);
  } catch {
    return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(displayDate);
  }
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function aggregateThemes(products: DashboardProduct[], key: "negativeFeedback" | "problems"): ProductTheme[] {
  const counts = new Map<string, number>();
  products.forEach((product) => product[key].forEach((item) => counts.set(item.label, (counts.get(item.label) ?? 0) + item.count)));
  return [...counts.entries()].map(([label, count]) => ({ label, subtopic: null, count })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function HorizontalBars({ items, tone, empty }: { items: Array<{ label: string; count: number }>; tone: "rating" | "feedback" | "problem"; empty: string }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  if (!items.length) return <p className="pulse-empty">{empty}</p>;
  return (
    <div className={`pulse-bars pulse-bars--${tone}`}>
      {items.map((item) => (
        <div className="pulse-bar" key={item.label}>
          <span>{item.label}</span>
          <i><b style={{ width: `${Math.max(2, (item.count / max) * 100)}%` }} /></i>
          <strong>{item.count.toLocaleString()}</strong>
        </div>
      ))}
    </div>
  );
}

export function Dashboard({ data }: DashboardProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => data.products.map((product) => product.id));

  useEffect(() => setSelectedIds(data.products.map((product) => product.id)), [data]);

  const selectedProducts = useMemo(() => data.products.filter((product) => selectedIds.includes(product.id)), [data.products, selectedIds]);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedEvidence = data.evidence.filter((item) => item.productId === null || selectedSet.has(item.productId));
  const totals = selectedProducts.reduce((result, product) => ({
    feedback: result.feedback + product.current.feedback,
    complaints: result.complaints + product.current.complaints,
    positive: result.positive + product.current.positive,
  }), { feedback: 0, complaints: 0, positive: 0 });
  const weightedRatings = selectedProducts.reduce((result, product) => ({
    total: result.total + (product.rating ?? 0) * (product.ratingCount ?? 0),
    count: result.count + (product.ratingCount ?? 0),
  }), { total: 0, count: 0 });
  const averageRating = weightedRatings.count ? weightedRatings.total / weightedRatings.count : null;
  const atRisk = selectedProducts.filter((product) => (ratio(product.current.complaints, product.current.feedback) ?? 0) >= .1 || (product.sentimentDelta ?? 0) <= -10);
  const ratingCounts = new Map<number, number>([5, 4, 3, 2, 1].map((rating) => [rating, 0]));
  selectedProducts.forEach((product) => product.ratingDistribution.forEach((item) => ratingCounts.set(item.rating, (ratingCounts.get(item.rating) ?? 0) + item.count)));
  const ratingDistribution = [5, 4, 3, 2, 1].map((rating) => ({ label: `${rating} star${rating === 1 ? "" : "s"}`, count: ratingCounts.get(rating) ?? 0 })).filter((item) => item.count > 0);
  const negativeFeedback = aggregateThemes(selectedProducts, "negativeFeedback").slice(0, 5).map((item) => ({ ...item, label: humanize(item.label) }));
  const problems = aggregateThemes(selectedProducts, "problems").slice(0, 5).map((item) => ({ ...item, label: humanize(item.label) }));
  const productsToWatch = [...selectedProducts].sort((a, b) => (ratio(b.current.complaints, b.current.feedback) ?? 0) - (ratio(a.current.complaints, a.current.feedback) ?? 0)).slice(0, 3);
  const heroProduct = productsToWatch[0];
  const incompleteMetadata = selectedProducts.filter((product) => !product.metadataComplete);

  return (
    <>
      {data.dataState === "partial" && <section className="truth-banner truth-banner--partial" role="status"><WarningCircle size={21} weight="fill" /><div><strong>Partial dashboard</strong><p>{data.messages[0] ?? "The backend returned usable data with incomplete coverage."}</p></div></section>}

      <section className="portfolio-toolbar" aria-label="Product portfolio scope">
        <div><span className="eyebrow">Live portfolio view</span><strong>Guardian customer feedback intelligence</strong><small>{dateLabel(data.windows.currentStart, { timeZone: data.windows.businessTimezone })} — {dateLabel(data.windows.currentEnd, { exclusiveEnd: true, timeZone: data.windows.businessTimezone })}</small></div>
        <ProductFilter products={data.products} selectedIds={selectedIds} onChange={setSelectedIds} />
      </section>

      {selectedProducts.length === 0 ? (
        <section className="empty-cohort"><Package size={28} /><h2>No products selected</h2><p>Select one or more products to build the Customer Pulse view.</p><button className="primary-button" type="button" onClick={() => setSelectedIds(data.products.map((product) => product.id))}>Show all products</button></section>
      ) : (
        <div className="pulse-overview">
          <section className="pulse-hero" aria-labelledby="pulse-title">
            <span className="pulse-hero__badge"><Star size={28} weight="fill" /></span>
            <div><span className="eyebrow">Executive summary · Current server window</span><h2 id="pulse-title">{data.primaryInsight?.title ?? "Customer feedback portfolio is ready for review"}</h2><p>{data.primaryInsight?.summary ?? `${totals.feedback.toLocaleString()} verified feedback items across ${selectedProducts.length} selected products.`}</p></div>
            {heroProduct && <button type="button" onClick={() => setSelectedIds([heroProduct.id])}>Focus top risk <ArrowRight size={16} weight="bold" /></button>}
            <span className="pulse-hero__art" aria-hidden="true"><Drop size={58} weight="duotone" /></span>
          </section>

          <section className="pulse-kpis" aria-label="Executive portfolio metrics">
            <article className="pulse-kpi pulse-kpi--blue"><span><ChatCircleDots size={24} weight="duotone" /></span><div><small>Feedback analyzed</small><strong>{totals.feedback.toLocaleString()}</strong><em>current server window</em></div></article>
            <article className="pulse-kpi pulse-kpi--green"><span><Star size={24} weight="fill" /></span><div><small>Average rating</small><strong>{averageRating === null ? "—" : averageRating.toFixed(2)}<i>/ 5</i></strong><em>{weightedRatings.count.toLocaleString()} rated reviews</em></div></article>
            <article className="pulse-kpi pulse-kpi--orange"><span><TrendDown size={24} weight="bold" /></span><div><small>Complaints</small><strong>{totals.complaints.toLocaleString()}</strong><em>{percent(ratio(totals.complaints, totals.feedback))} of feedback</em></div></article>
            <article className="pulse-kpi pulse-kpi--red"><span><WarningCircle size={24} weight="fill" /></span><div><small>Products at risk</small><strong>{atRisk.length}</strong><em>need executive attention</em></div></article>
          </section>

          <section className="pulse-chart-grid">
            <article className="pulse-card"><header><div><span className="eyebrow">Customer selection</span><h3>Star rating distribution</h3></div><small>{averageRating === null ? "No average" : `${averageRating.toFixed(2)} avg.`}</small></header><p>Actual star selections in the current window</p><HorizontalBars items={ratingDistribution} tone="rating" empty="No star ratings were supplied for this selection." /></article>
            <article className="pulse-card"><header><div><span className="eyebrow">Voice of customer</span><h3>Top 5 negative feedback</h3></div><small>{totals.complaints.toLocaleString()} complaints</small></header><p>High-level complaint topics from server classification</p><HorizontalBars items={negativeFeedback} tone="feedback" empty="No classified complaint topics are available." /></article>
            <article className="pulse-card"><header><div><span className="eyebrow">Operational diagnosis</span><h3>Top 5 product problems</h3></div><small>Prioritized</small></header><p>Specific subtopics teams can act on</p><HorizontalBars items={problems} tone="problem" empty="No specific problem subtopics are available." /></article>
          </section>

          {incompleteMetadata.length > 0 && <section className="metadata-notice" role="note"><Info size={20} weight="fill" /><div><strong>Product catalog details are incomplete</strong><p>{incompleteMetadata.length} selected product group(s) only include metadata supplied by ingestion.</p></div></section>}

          <section className="pulse-lower-grid">
            <article className="pulse-card products-watch"><header><div><span className="eyebrow">Priority queue</span><h3>Products to watch</h3></div><small>Complaint rate</small></header><div className="watch-list">{productsToWatch.map((product, index) => <button className="watch-product" type="button" key={product.id} onClick={() => setSelectedIds([product.id])}><span className="watch-product__icon"><Package size={23} weight="duotone" /></span><span><small>0{index + 1} · {product.category ?? "Category unavailable"}</small><strong>{productName(product)}</strong><em>{humanize(product.problems[0]?.label ?? "No dominant problem")}</em></span><b>{percent(ratio(product.current.complaints, product.current.feedback), 0)}<i> complaint rate</i></b></button>)}</div></article>
            <article className="pulse-card benchmark-card"><header><div><span className="eyebrow">Competitive context</span><h3>Global comparable benchmark</h3></div><small>Portfolio-wide</small></header><p className="benchmark-scope-note">This benchmark covers the complete matched portfolio cohort{selectedProducts.length !== data.products.length ? "; the current product selection is narrower" : ""}.</p>{!data.benchmark?.comparable ? <p className="pulse-empty">{data.benchmark?.reason ?? "Comparison not available."}</p> : <div className="benchmark-ratings">{data.benchmark.brands.map((brand) => <div key={brand.brand}><span>{humanize(brand.brand)}</span><i><b style={{ width: `${((brand.rating ?? 0) / 5) * 100}%` }} /></i><strong>{brand.rating === null ? "—" : brand.rating.toFixed(2)}</strong></div>)}</div>}</article>
          </section>

          <section className="pulse-card evidence-panel"><header><div><span className="eyebrow">Customer evidence</span><h3>Reported excerpts</h3></div><small>{selectedEvidence.length} returned</small></header>{selectedEvidence.length ? <div className="evidence-list">{selectedEvidence.slice(0, 6).map((item) => <blockquote key={item.id}><p>“{item.text}”</p><footer>{item.sourcePlatform} · {humanize(item.sourceGroup)}{item.timestamp ? ` · ${dateLabel(item.timestamp)}` : ""}</footer></blockquote>)}</div> : <p className="pulse-empty">No redacted evidence excerpts were returned for this selection.</p>}</section>

          {data.primaryInsight && <section className="primary-insight pulse-decision"><div className="primary-insight__icon"><Pulse size={25} weight="fill" /></div><div><span className="eyebrow">Executive action</span><div className="primary-insight__labels">{data.primaryInsight.label && <span className={`decision-label decision-label--${data.primaryInsight.label}`}>{humanize(data.primaryInsight.label)} decision</span>}{data.primaryInsight.status && <span className="workflow-status">Workflow: {humanize(data.primaryInsight.status)}</span>}</div><h2>Recommended next steps</h2>{data.primaryInsight.recommendedActions.length > 0 && <ul>{data.primaryInsight.recommendedActions.map((action) => <li key={action}>{action}</li>)}</ul>}</div></section>}

          {data.messages.length > (data.dataState === "partial" ? 1 : 0) && <section className="server-notes"><Database size={19} /><div><strong>Backend data notes</strong><ul>{data.messages.slice(data.dataState === "partial" ? 1 : 0).map((message) => <li key={message}>{message}</li>)}</ul></div></section>}
        </div>
      )}
    </>
  );
}
