import type { DashboardData, DashboardEvidence, DashboardProduct, ProductTheme } from "../api/types";

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function formatDateTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function percent(value: number | null): string {
  return value === null ? "-" : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function rows(items: Array<Array<unknown>>): string {
  return items.map((item) => `<tr>${item.map((cell) => `<td>${escapeHtml(display(cell))}</td>`).join("")}</tr>`).join("");
}

function themeList(items: ProductTheme[] | undefined): string {
  if (!items?.length) return "-";
  return items.map((item) => `${item.label}: ${item.count.toLocaleString()}${item.baselineCount ? ` (baseline ${item.baselineCount.toLocaleString()})` : ""}`).join("; ");
}

function productName(product: DashboardProduct): string {
  return product.shortName ?? product.name ?? product.id;
}

function evidenceProductName(item: DashboardEvidence, productsById: Map<string, DashboardProduct>): string {
  return item.productId ? productName(productsById.get(item.productId) ?? ({ id: item.productId } as DashboardProduct)) : "-";
}

export function buildDashboardPdfReportHtml(data: DashboardData): string {
  const productsById = new Map(data.products.map((product) => [product.id, product]));
  const productRows = data.products.map((product) => [
    productName(product),
    product.sku,
    product.category,
    product.pack,
    product.rating,
    product.ratingCount,
    product.totalFeedback,
    product.current.feedback,
    product.current.positive,
    product.current.neutral,
    product.current.complaints,
    product.baseline.feedback,
    product.baseline.complaints,
    product.sentimentDelta,
  ]);
  const detailSections = data.products.map((product) => `
    <section class="break-avoid">
      <h3>${escapeHtml(productName(product))}</h3>
      <table>
        <tbody>
          ${rows([
            ["Product ID", product.id], ["SKU", product.sku], ["Category", product.category], ["Pack", product.pack],
            ["Metadata complete", product.metadataComplete], ["Rating", product.rating], ["Rating count", product.ratingCount],
            ["Sources", product.sources.map((source) => `${source.sourceGroup}: ${source.count.toLocaleString()}`).join("; ")],
            ["Themes", themeList(product.themes)], ["Current problems", themeList(product.problems)],
            ["All problems", themeList(product.allProblems)], ["Negative feedback", themeList(product.negativeFeedback)],
            ["Rating distribution", product.ratingDistribution.map((item) => `${item.rating} star: ${item.count}`).join("; ")],
            ["Baseline rating distribution", product.baselineRatingDistribution.map((item) => `${item.rating} star: ${item.count}`).join("; ")],
            ["All rating distribution", product.allRatingDistribution?.map((item) => `${item.rating} star: ${item.count}`).join("; ")],
            ["Rating trend", product.ratingTrend.map((point) => `${point.date} ${point.platform}: ${point.averageRating.toFixed(2)} (${point.count}${point.predicted ? ", predicted" : ""})`).join("; ")],
          ])}
        </tbody>
      </table>
    </section>
  `).join("");
  const evidenceRows = data.evidence.map((item) => [
    evidenceProductName(item, productsById),
    item.sourcePlatform || item.sourceGroup,
    formatDateTime(item.timestamp),
    item.sentiment,
    item.topic,
    item.subtopic,
    item.stance,
    item.confidence === null ? null : percent(item.confidence),
    item.text,
    item.sourceUrl,
  ]);
  const benchmarkRows = data.benchmark?.brands.map((brand) => [
    brand.brand,
    brand.feedback,
    brand.complaints,
    brand.positive,
    brand.neutral,
    brand.rating,
    brand.ratingCount,
    brand.share === null ? null : percent(brand.share),
  ]) ?? [];

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Guardian dashboard export ${escapeHtml(data.asOf ?? "")}</title>
  <style>
    @page { size: A4; margin: 14mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #1f2937; font: 12px/1.45 Inter, Arial, sans-serif; }
    h1 { margin: 0 0 4px; color: #111827; font-size: 24px; line-height: 1.2; }
    h2 { margin: 24px 0 8px; color: #111827; font-size: 16px; break-after: avoid; }
    h3 { margin: 18px 0 6px; color: #111827; font-size: 13px; break-after: avoid; }
    p { margin: 4px 0; }
    table { width: 100%; border-collapse: collapse; margin: 8px 0 14px; table-layout: fixed; }
    th, td { border: 1px solid #d1d5db; padding: 5px 6px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
    th { background: #f3f4f6; color: #111827; font-weight: 700; }
    .meta { color: #4b5563; margin-bottom: 18px; }
    .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
    .card { border: 1px solid #d1d5db; padding: 10px; break-inside: avoid; }
    .metric { color: #111827; font-size: 18px; font-weight: 760; }
    .break-avoid { break-inside: avoid; }
    .page-break { break-before: page; }
    @media print { button { display: none; } }
  </style>
</head>
<body>
  <h1>Guardian VOC Dashboard</h1>
  <p class="meta">Exported ${escapeHtml(formatDateTime(new Date().toISOString()))} · Data as of ${escapeHtml(formatDateTime(data.asOf))} · Last updated ${escapeHtml(formatDateTime(data.lastUpdated))}</p>

  <section class="grid">
    <div class="card"><p>Mode</p><p class="metric">${escapeHtml(data.mode)}</p></div>
    <div class="card"><p>Health</p><p class="metric">${escapeHtml(data.overallHealth)}</p></div>
    <div class="card"><p>Data state</p><p class="metric">${escapeHtml(data.dataState)}</p></div>
    <div class="card"><p>Products</p><p class="metric">${data.products.length.toLocaleString()}</p></div>
  </section>

  <h2>Coverage</h2>
  <table><tbody>${rows([
    ["Feedback items", data.coverage.feedbackItems], ["Analyzed items", data.coverage.analyzedItems],
    ["Relevant items", data.coverage.relevantItems], ["Time eligible items", data.coverage.timeEligibleItems],
    ["Product attributed items", data.coverage.productAttributedItems],
  ])}</tbody></table>

  <h2>Analysis Windows</h2>
  <table><tbody>${rows([
    ["Current start", formatDateTime(data.windows.currentStart)], ["Current end", formatDateTime(data.windows.currentEnd)],
    ["Baseline start", formatDateTime(data.windows.baselineStart)], ["Baseline end", formatDateTime(data.windows.baselineEnd)],
    ["Business timezone", data.windows.businessTimezone],
  ])}</tbody></table>

  <h2>Primary Insight</h2>
  <table><tbody>${data.primaryInsight ? rows([
    ["Title", data.primaryInsight.title], ["Summary", data.primaryInsight.summary], ["Topic", data.primaryInsight.topic],
    ["Label", data.primaryInsight.label], ["Status", data.primaryInsight.status],
    ["Confidence", data.primaryInsight.confidenceLevel], ["Confidence score", data.primaryInsight.confidenceScore],
    ["Current share", data.primaryInsight.currentShare === null ? null : percent(data.primaryInsight.currentShare)],
    ["Baseline share", data.primaryInsight.baselineShare === null ? null : percent(data.primaryInsight.baselineShare)],
    ["Percentage point change", data.primaryInsight.percentagePointChange],
    ["Growth multiple", data.primaryInsight.growthMultiple],
    ["Recommended actions", data.primaryInsight.recommendedActions.join("; ")],
  ]) : rows([["Insight", "No primary insight available"]])}</tbody></table>

  <h2>Benchmark</h2>
  <p>${escapeHtml(data.benchmark?.comparable ? "Comparable benchmark available." : data.benchmark?.reason ?? "No benchmark available.")}</p>
  <table><thead><tr><th>Brand</th><th>Feedback</th><th>Complaints</th><th>Positive</th><th>Neutral</th><th>Rating</th><th>Rating count</th><th>Share</th></tr></thead><tbody>${rows(benchmarkRows)}</tbody></table>

  <h2 class="page-break">Products</h2>
  <table><thead><tr><th>Product</th><th>SKU</th><th>Category</th><th>Pack</th><th>Rating</th><th>Rating count</th><th>Total feedback</th><th>Current feedback</th><th>Current positive</th><th>Current neutral</th><th>Current complaints</th><th>Baseline feedback</th><th>Baseline complaints</th><th>Sentiment delta</th></tr></thead><tbody>${rows(productRows)}</tbody></table>
  ${detailSections}

  <h2 class="page-break">Evidence</h2>
  <table><thead><tr><th>Product</th><th>Source</th><th>Timestamp</th><th>Sentiment</th><th>Topic</th><th>Subtopic</th><th>Stance</th><th>Confidence</th><th>Text</th><th>URL</th></tr></thead><tbody>${rows(evidenceRows)}</tbody></table>

  <h2>Backend Messages</h2>
  <table><tbody>${rows((data.messages.length ? data.messages : ["No backend messages."]).map((message) => ["Message", message]))}</tbody></table>
</body>
</html>`;
}

export function openDashboardPdfReport(data: DashboardData): boolean {
  const reportWindow = window.open("", "_blank");
  if (!reportWindow) return false;
  reportWindow.document.open();
  reportWindow.document.write(buildDashboardPdfReportHtml(data));
  reportWindow.document.close();
  reportWindow.focus();
  reportWindow.print();
  return true;
}
