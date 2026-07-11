import { formatPercent, SOURCE_LABELS, type deriveDashboard } from "./data/dashboard";

type DashboardData = ReturnType<typeof deriveDashboard>;

export type ExecutiveReportType = "portfolio" | "focused";

function escapeHtml(value: string | number | null | undefined) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function reportDate(date: Date) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function fileDate(date: Date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

function rate(complaints: number, reviews: number) {
  return reviews ? (complaints / reviews) * 100 : 0;
}

function statusLabel(status: DashboardData["status"]) {
  if (status === "critical") return "Critical";
  if (status === "watch") return "Needs attention";
  if (status === "improving") return "Improving";
  return "No status";
}

function metric(label: string, value: string, detail: string, tone = "") {
  return `<div class="metric ${tone}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></div>`;
}

function portfolioBody(data: DashboardData) {
  const rankedProducts = [...data.selectedProducts]
    .sort((a, b) => rate(b.current.complaints, b.current.reviews) - rate(a.current.complaints, a.current.reviews))
    .slice(0, 6);
  const aboveBaseline = data.selectedProducts.filter((product) =>
    rate(product.current.complaints, product.current.reviews) > rate(product.baseline.complaints, product.baseline.reviews),
  ).length;
  const topProduct = rankedProducts[0];

  return `
    <section class="summary-block">
      <div>
        <p class="kicker">Executive summary</p>
        <h2>${escapeHtml(topProduct?.shortName ?? "Portfolio")} carries the highest current complaint risk</h2>
        <p>The portfolio is at <strong>${escapeHtml(formatPercent(data.complaintShare))} complaint share</strong> in the current 72-hour window, compared with ${escapeHtml(formatPercent(data.baselineShare))} in the 28-day baseline.</p>
      </div>
      <span class="status status--${escapeHtml(data.status)}">${escapeHtml(statusLabel(data.status))}</span>
    </section>

    <section class="metrics">
      ${metric("Complaint share", formatPercent(data.complaintShare), `${data.currentComplaints} of ${data.currentReviews} reviews`, "critical")}
      ${metric("Issue velocity", data.velocity === null ? "-" : `${data.velocity.toFixed(1)}x`, "Current vs baseline")}
      ${metric("Above baseline", String(aboveBaseline), `of ${data.selectedProducts.length} products`)}
      ${metric("Feedback channels", String(data.sourceCounts.filter((source) => source.count > 0).length), "Independent sources")}
    </section>

    <section class="report-section keep-together">
      <div class="section-head"><div><p class="kicker">Risk ranking</p><h2>Products requiring attention</h2></div><span>Top 6 by complaint rate</span></div>
      <table>
        <thead><tr><th>Product</th><th>Current</th><th>Baseline</th><th>Change</th><th>Top problem</th></tr></thead>
        <tbody>
          ${rankedProducts.map((product) => {
            const current = rate(product.current.complaints, product.current.reviews);
            const baseline = rate(product.baseline.complaints, product.baseline.reviews);
            return `<tr><td><strong>${escapeHtml(product.shortName)}</strong><small>${escapeHtml(product.sku)}</small></td><td>${current.toFixed(1)}%</td><td>${baseline.toFixed(1)}%</td><td class="${current > baseline ? "bad" : "good"}">${current > baseline ? "+" : ""}${(current - baseline).toFixed(1)}pp</td><td>${escapeHtml(product.themes[0]?.label ?? "No dominant issue")}</td></tr>`;
          }).join("")}
        </tbody>
      </table>
    </section>

    <div class="two-column">
      <section class="report-section keep-together">
        <p class="kicker">Customer signals</p><h2>Top issue themes</h2>
        <ol class="rank-list">${data.themes.slice(0, 4).map((theme) => `<li><span>${escapeHtml(theme.label)}</span><strong>${theme.count} mentions</strong></li>`).join("")}</ol>
      </section>
      <section class="report-section decision keep-together">
        <p class="kicker">Decision needed</p><h2>Authorize immediate review</h2>
        <p>Confirm Quality Assurance and E-commerce Operations ownership for the highest-risk products within 24 hours.</p>
        <strong>Success signal</strong><span>Complaint share returns toward the 28-day baseline.</span>
      </section>
    </div>`;
}

function focusedBody(data: DashboardData) {
  const hypothesis = data.hypotheses[0];
  const action = data.recommendedAction;
  const products = data.selectedProducts.map((product) => product.shortName).join(" + ");

  return `
    <section class="summary-block">
      <div>
        <p class="kicker">Incident summary</p>
        <h2>${escapeHtml(data.headline.replaceAll("×", "x"))}</h2>
        <p>Affected scope: <strong>${escapeHtml(products)}</strong>. The report reflects the selected 72-hour customer-feedback cohort.</p>
      </div>
      <span class="status status--${escapeHtml(data.status)}">${escapeHtml(statusLabel(data.status))}</span>
    </section>

    <section class="metrics">
      ${metric("Complaints", `${data.currentComplaints}/${data.currentReviews}`, "Affected cohort", "critical")}
      ${metric("Complaint rate", formatPercent(data.complaintShare), `Baseline ${formatPercent(data.baselineShare)}`, "critical")}
      ${metric("Issue velocity", data.velocity === null ? "-" : `${data.velocity.toFixed(1)}x`, "Current vs baseline")}
      ${metric("Affected SKUs", String(data.selectedProducts.length), products)}
    </section>

    <section class="report-section keep-together">
      <div class="section-head"><div><p class="kicker">Customer impact</p><h2>Top customer problems</h2></div><span>${data.currentComplaints} complaints</span></div>
      <div class="problem-grid">${data.themes.slice(0, 3).map((theme, index) => `<div><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(theme.label)}</strong><small>${theme.count} customer mentions</small></div>`).join("")}</div>
    </section>

    <div class="two-column">
      <section class="report-section hypothesis keep-together">
        <p class="kicker">Root-cause hypothesis</p><h2>${escapeHtml(hypothesis?.title ?? "More evidence required")}</h2>
        <p>${escapeHtml(hypothesis?.summary ?? "The selected cohort does not yet support a defensible hypothesis.")}</p>
        ${hypothesis ? `<div class="confidence"><strong>${Math.round(hypothesis.confidence * 100)}%</strong><span>AI confidence<br>${hypothesis.support} supporting / ${hypothesis.contradict} contradicting signals</span></div>` : ""}
      </section>
      <section class="report-section decision keep-together">
        <p class="kicker">Decision needed</p><h2>${escapeHtml(action?.title ?? "Continue evidence collection")}</h2>
        <p>${escapeHtml(action?.summary ?? "Assign an owner to validate the incident before operational escalation.")}</p>
        <strong>Proposed owner</strong><span>${escapeHtml(action?.owner ?? "Customer Experience")}${action?.dueDate ? ` - due ${escapeHtml(action.dueDate)}` : ""}</span>
      </section>
    </div>

    <section class="report-section report-page-break keep-together">
      <div class="section-head"><div><p class="kicker">Corrective action</p><h2>Recommended next steps</h2></div><span>${escapeHtml(action?.priority ?? "Needs evidence")} priority</span></div>
      <ol class="action-list">${(action?.steps ?? ["Collect more independent evidence before assigning a corrective action."]).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
    </section>

    <section class="report-section keep-together">
      <div class="section-head"><div><p class="kicker">Customer evidence</p><h2>Representative reports</h2></div><span>Confidence-ranked sample</span></div>
      <div class="quotes">${data.evidence.filter((item) => item.stance === "support").slice(0, 3).map((item) => `<blockquote><p>&ldquo;${escapeHtml(item.quote)}&rdquo;</p><footer>${escapeHtml(SOURCE_LABELS[item.source])} - ${Math.round(item.confidence * 100)}% match</footer></blockquote>`).join("")}</div>
    </section>`;
}

export function buildExecutiveReportHtml(data: DashboardData, type: ExecutiveReportType, generatedAt = new Date()) {
  const isPortfolio = type === "portfolio";
  const title = isPortfolio ? "Guardian Portfolio Health Report" : "Guardian Critical Incident Brief";
  const fileTitle = isPortfolio
    ? `Guardian_Portfolio_Report_${fileDate(generatedAt)}`
    : `Guardian_Incident_${data.selectedProducts[0]?.sku ?? "Selected-Scope"}_${fileDate(generatedAt)}`;
  const body = isPortfolio ? portfolioBody(data) : focusedBody(data);

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(fileTitle)}</title>
<style>
  @page { size: A4; margin: 13mm 14mm 15mm; }
  * { box-sizing: border-box; }
  html { color: #171918; background: #fff; font-family: Inter, Arial, sans-serif; }
  body { width: 100%; margin: 0; font-size: 10pt; line-height: 1.45; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18mm; padding-bottom: 7mm; border-bottom: 2px solid #f67e2a; }
  header h1 { margin: 1.5mm 0 1mm; font-size: 22pt; line-height: 1.06; letter-spacing: -.035em; }
  header p { margin: 0; color: #626971; }
  .brand { color: #f04a3e; font-size: 9pt; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
  .meta { min-width: 45mm; text-align: right; }
  .meta strong, .meta span { display: block; }
  .meta strong { margin-bottom: 1.5mm; font-size: 9pt; }
  .meta span { color: #737a82; font-size: 8pt; }
  .demo { display: inline-block; margin-top: 2mm; padding: 1.3mm 2.5mm; border: 1px solid #e4bd72; border-radius: 99px; color: #704c05 !important; background: #fff7df; font-weight: 700; }
  .summary-block { display: flex; align-items: flex-start; justify-content: space-between; gap: 9mm; margin: 7mm 0 5mm; padding: 6mm; border-left: 3px solid #df342e; background: #f7f7f7; }
  .summary-block > div { flex: 1; min-width: 0; }
  .summary-block h2 { margin: 1mm 0 2mm; font-size: 17pt; line-height: 1.15; letter-spacing: -.025em; }
  .summary-block p { margin: 0; color: #50565d; }
  .kicker { margin: 0 !important; color: #777e85 !important; font-size: 7.5pt; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }
  .status { flex: 0 0 auto; padding: 2mm 3.5mm; border-radius: 99px; color: #fff; background: #df342e; font-size: 8pt; font-weight: 800; }
  .status--watch { color: #352002; background: #f67e2a; }
  .status--improving { background: #248443; }
  .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 6mm; border: 1px solid #d9dde0; border-radius: 2mm; }
  .metric { min-width: 0; padding: 4mm; border-left: 1px solid #d9dde0; }
  .metric:first-child { border-left: 0; }
  .metric span, .metric small, .metric strong { display: block; }
  .metric span { color: #737a82; font-size: 7pt; font-weight: 800; text-transform: uppercase; }
  .metric strong { margin: 1mm 0 .5mm; font-size: 17pt; line-height: 1; letter-spacing: -.03em; }
  .metric small { overflow-wrap: anywhere; color: #737a82; font-size: 7.5pt; }
  .metric.critical strong, .bad { color: #df342e; }
  .good { color: #248443; }
  .report-section { margin-top: 5mm; padding-top: 4mm; border-top: 1px solid #d9dde0; }
  .report-section h2 { margin: 1mm 0 3mm; font-size: 13pt; line-height: 1.2; }
  .section-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 8mm; }
  .section-head > span { color: #737a82; font-size: 8pt; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 8.3pt; }
  th { padding: 2.2mm; color: #737a82; background: #f1f2f3; font-size: 7pt; text-align: left; text-transform: uppercase; }
  th:first-child { width: 30%; } th:last-child { width: 22%; }
  td { padding: 2.4mm 2.2mm; border-bottom: 1px solid #e5e7e8; vertical-align: top; overflow-wrap: anywhere; }
  td strong, td small { display: block; } td small { margin-top: .5mm; color: #7a8087; font-size: 7pt; }
  .two-column { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6mm; }
  .rank-list, .action-list { margin: 0; padding: 0; list-style: none; }
  .rank-list li { display: flex; justify-content: space-between; gap: 4mm; padding: 2.2mm 0; border-bottom: 1px solid #e5e7e8; }
  .rank-list strong { color: #626971; font-size: 8pt; white-space: nowrap; }
  .decision { padding: 5mm; border: 1px solid #f0c4a5; border-top: 3px solid #f67e2a; background: #fff8f2; }
  .decision p { color: #50565d; }
  .decision > strong, .decision > span { display: block; }
  .decision > strong { margin-top: 3mm; font-size: 8pt; text-transform: uppercase; }
  .decision > span { margin-top: 1mm; color: #50565d; }
  .problem-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 3mm; }
  .problem-grid > div { min-width: 0; padding: 4mm; border: 1px solid #d9dde0; border-top: 3px solid #df342e; border-radius: 1.5mm; }
  .problem-grid span, .problem-grid strong, .problem-grid small { display: block; }
  .problem-grid span { color: #df342e; font-size: 8pt; font-weight: 800; }
  .problem-grid strong { margin: 2mm 0 1mm; font-size: 11pt; overflow-wrap: anywhere; }
  .problem-grid small { color: #737a82; }
  .hypothesis p { color: #50565d; }
  .confidence { display: flex; align-items: center; gap: 3mm; margin-top: 4mm; padding: 3mm; border-radius: 2mm; background: #f4eff9; }
  .confidence strong { color: #7650a0; font-size: 17pt; }
  .confidence span { color: #626971; font-size: 7.5pt; }
  .action-list { counter-reset: steps; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 3mm; }
  .action-list li { counter-increment: steps; min-width: 0; padding: 4mm; border: 1px solid #d9dde0; border-radius: 1.5mm; overflow-wrap: anywhere; }
  .action-list li::before { display: grid; width: 6mm; height: 6mm; margin-bottom: 2.5mm; place-items: center; border-radius: 50%; color: #171918; background: #f67e2a; content: counter(steps); font-size: 8pt; font-weight: 800; }
  .quotes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 3mm; }
  blockquote { min-width: 0; margin: 0; padding: 3.5mm; border-left: 2px solid #7650a0; background: #f7f4fa; }
  blockquote p { margin: 0; overflow-wrap: anywhere; font-size: 8.5pt; }
  blockquote footer { margin-top: 2mm; color: #737a82; font-size: 7pt; }
  .document-footer { display: flex; justify-content: space-between; gap: 8mm; margin-top: 7mm; padding-top: 3mm; border-top: 1px solid #d9dde0; color: #7a8087; font-size: 7pt; }
  .keep-together { break-inside: avoid; page-break-inside: avoid; }
  @media print {
    .keep-together { break-inside: avoid-page; }
    .report-page-break { margin-top: 0; break-before: page; page-break-before: always; }
  }
</style></head>
<body>
  <header><div><span class="brand">Guardian Customer Intelligence</span><h1>${escapeHtml(title)}</h1><p>${escapeHtml(data.scopeLabel)} - Last 72 hours</p></div><div class="meta"><strong>Generated ${escapeHtml(reportDate(generatedAt))}</strong><span>Current filters and selected scope</span><span class="demo">Synthetic demo data</span></div></header>
  ${body}
  <footer class="document-footer"><span>Internal management report</span><span>Validate source matching and deduplication before operational use.</span></footer>
  <script>window.addEventListener("load", function () { window.setTimeout(function () { window.focus(); window.print(); }, 180); });<\/script>
</body></html>`;
}

export function openExecutiveReport(data: DashboardData, type: ExecutiveReportType) {
  const reportWindow = window.open("", "guardian-report-preview", "width=1080,height=820");
  if (!reportWindow) return false;
  reportWindow.document.open();
  reportWindow.document.write(buildExecutiveReportHtml(data, type));
  reportWindow.document.close();
  return true;
}
