import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowSquareOut, X } from "@phosphor-icons/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  ReferenceLine,
  Sector,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PieSectorShapeProps } from "recharts";
import {
  FEEDBACK_WINDOWS,
  FEEDBACK_WINDOW_LABELS,
  SOURCE_LABELS,
  projectProductToPreviousWindow,
  projectProductToWindow,
  type FeedbackWindow,
  type Product,
  type SourceKey,
} from "../data/dashboard";
import { TimeRangeSelect } from "./TimeRangeSelect";

const FALLBACK_PROBLEMS = [
  "Delivery damage",
  "Seal quality",
  "Packaging deformation",
  "Product leakage",
  "Wrong item received",
  "Late delivery",
  "Texture concern",
  "Skin irritation",
  "Strong scent",
  "Missing accessory",
];

const SOURCE_ORDER: SourceKey[] = ["app", "marketplace", "service", "social"];
const PROBLEM_COLORS = ["#e33b36", "#f67e2a", "#d28a32", "#9d6db0", "#7650a0", "#388da0", "#197b8a", "#4d9364", "#7b8f52", "#8a7c70"];
const SHOW_LEGACY_PROBLEM_PIE = false; // Keep the original share view available while time comparison is prioritized.

export type ProblemReviewSelection = { label: string; count: number };
type Problem = ProblemReviewSelection;
type ProblemTooltipProps = {
  active?: boolean;
  payload?: Array<{ payload: Problem }>;
  total: number;
};
type Review = {
  id: string;
  source: SourceKey;
  page: string;
  timestamp: string;
  text: string;
  problem: string;
};

type MonthlySentiment = {
  month: string;
  year: number;
  positive: number;
  neutral: number;
  negative: number;
  reviews: number;
};

const MONTHS = [
  { month: "Aug", year: 2024 },
  { month: "Sep", year: 2024 },
  { month: "Oct", year: 2024 },
  { month: "Nov", year: 2024 },
  { month: "Dec", year: 2024 },
  { month: "Jan", year: 2025 },
  { month: "Feb", year: 2025 },
  { month: "Mar", year: 2025 },
  { month: "Apr", year: 2025 },
  { month: "May", year: 2025 },
  { month: "Jun", year: 2025 },
  { month: "Jul", year: 2025 },
  { month: "Aug", year: 2025 },
  { month: "Sep", year: 2025 },
  { month: "Oct", year: 2025 },
  { month: "Nov", year: 2025 },
  { month: "Dec", year: 2025 },
  { month: "Jan", year: 2026 },
  { month: "Feb", year: 2026 },
  { month: "Mar", year: 2026 },
  { month: "Apr", year: 2026 },
  { month: "May", year: 2026 },
  { month: "Jun", year: 2026 },
  { month: "Jul", year: 2026 },
];
const SENTIMENT_RANGES = [
  { value: "3m", label: "Last 3 months", months: 3 },
  { value: "6m", label: "Last 6 months", months: 6 },
  { value: "12m", label: "Last 12 months", months: 12 },
] as const;
type SentimentRange = (typeof SENTIMENT_RANGES)[number]["value"];

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function buildMonthlySentiment(product: Product): MonthlySentiment[] {
  const complaintRate = product.current.reviews
    ? (product.current.complaints / product.current.reviews) * 100
    : 0;
  const currentNegative = clamp(Math.round(10 + complaintRate * 0.62), 8, 32);
  const startingNegative = clamp(
    Math.round(currentNegative + product.sentimentDelta * 0.45),
    6,
    34,
  );
  const productSeed = product.id.split("").reduce((total, character) => total + character.charCodeAt(0), 0);

  return MONTHS.map(({ month, year }, index) => {
    const progress = index / (MONTHS.length - 1);
    const wobble = index === MONTHS.length - 1 ? 0 : ((productSeed + index) % 3) - 1;
    const negative = clamp(
      Math.round(startingNegative + (currentNegative - startingNegative) * progress + wobble),
      5,
      36,
    );
    const neutral = clamp(15 + ((productSeed + index * 2) % 3) - 1, 12, 18);
    const reviews = Math.max(24, Math.round(product.current.reviews * (0.62 + index * (0.38 / (MONTHS.length - 1)))));
    return { month, year, positive: 100 - neutral - negative, neutral, negative, reviews };
  });
}

function SentimentTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string; payload: MonthlySentiment }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="sentiment-tooltip" role="status">
      <strong>{label} {payload[0].payload.year} · {payload[0].payload.reviews} reviews</strong>
      {payload.slice().reverse().map((item) => (
        <span key={item.name}><i style={{ background: item.color }} />{item.name} <b>{item.value}%</b></span>
      ))}
    </div>
  );
}

function MonthlySentimentChart({ product, compareMode }: { product: Product; compareMode: boolean }) {
  const [range, setRange] = useState<SentimentRange>("6m");
  const visibleMonths = SENTIMENT_RANGES.find((option) => option.value === range)?.months ?? 6;
  const data = useMemo(() => buildMonthlySentiment(product)
    .slice(-(compareMode ? visibleMonths * 2 : visibleMonths))
    .map((item) => ({
      ...item,
      axisLabel: compareMode ? `${item.month} '${String(item.year).slice(-2)}` : item.month,
    })), [compareMode, product, visibleMonths]);
  const latest = data.at(-1)!;
  const previous = data.at(-2)!;
  const currentPeriod = data.slice(-visibleMonths);
  const previousPeriod = compareMode ? data.slice(0, visibleMonths) : [];
  const averageNegative = (items: MonthlySentiment[]) => items.reduce((total, item) => total + item.negative, 0) / Math.max(items.length, 1);
  const negativeChange = compareMode
    ? averageNegative(currentPeriod) - averageNegative(previousPeriod)
    : latest.negative - previous.negative;
  const rangeLabel = SENTIMENT_RANGES.find((option) => option.value === range)?.label ?? "Last 6 months";

  return (
    <section className="product-sentiment" aria-labelledby="product-sentiment-title">
      <div className="product-sentiment__head">
        <div>
          <span className="step-label">Customer sentiment</span>
          <h3 id="product-sentiment-title">Monthly sentiment trend</h3>
          <p>How customer tone has shifted for this product over the selected period.</p>
        </div>
        <div className="product-sentiment__controls">
          <TimeRangeSelect
            ariaLabel="Filter sentiment trend by time"
            value={range}
            options={SENTIMENT_RANGES}
            onChange={setRange}
          />
          {compareMode && <span className="comparison-mode-label">Current vs previous {range}</span>}
          <div className="product-sentiment__summary" aria-label={`Latest sentiment: ${latest.positive}% positive, ${latest.neutral}% neutral and ${latest.negative}% negative`}>
            <span><i className="is-positive" />Positive <strong>{latest.positive}%</strong></span>
            <span><i className="is-neutral" />Neutral <strong>{latest.neutral}%</strong></span>
            <span><i className="is-negative" />Negative <strong>{latest.negative}%</strong></span>
          </div>
        </div>
      </div>

      <div
        className="product-sentiment__chart"
        role="img"
        aria-label={`Line chart of monthly sentiment for ${product.shortName} over ${rangeLabel.toLowerCase()}${compareMode ? ` compared with the previous ${visibleMonths} months` : ""}`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 16, right: 18, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke="var(--border-soft)" />
            <XAxis dataKey="axisLabel" interval="preserveStartEnd" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} unit="%" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
            <Tooltip content={<SentimentTooltip />} cursor={{ stroke: "var(--control-border-strong)", strokeDasharray: "4 4" }} />
            <Legend iconType="circle" wrapperStyle={{ fontSize: 10, color: "var(--muted)" }} />
            {compareMode && currentPeriod[0] && (
              <ReferenceLine
                x={currentPeriod[0].axisLabel}
                stroke="var(--control-border-strong)"
                strokeDasharray="4 4"
                label={{ value: "Current period", position: "insideTopRight", fill: "var(--muted)", fontSize: 9 }}
              />
            )}
            <Line type="monotone" dataKey="positive" name="Positive" stroke="#4d9364" strokeWidth={2.5} dot={{ r: 3, strokeWidth: 2, fill: "var(--surface)" }} activeDot={{ r: 5 }} />
            <Line type="monotone" dataKey="neutral" name="Neutral" stroke="#aeb5ba" strokeWidth={2.5} dot={{ r: 3, strokeWidth: 2, fill: "var(--surface)" }} activeDot={{ r: 5 }} />
            <Line type="monotone" dataKey="negative" name="Negative" stroke="#d93431" strokeWidth={2.5} dot={{ r: 3, strokeWidth: 2, fill: "var(--surface)" }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="product-sentiment__footer">
        <span><strong>{negativeChange > 0 ? "+" : ""}{negativeChange.toFixed(compareMode ? 1 : 0)}pp</strong> negative sentiment vs {compareMode ? "previous period" : previous.month}</span>
        <span>{latest.reviews} classified reviews in Jul · Synthetic demo</span>
      </div>
    </section>
  );
}

function buildProblems(product: Product): Problem[] {
  const seen = new Set(product.themes.map((theme) => theme.label.toLowerCase()));
  const fillers = FALLBACK_PROBLEMS.filter((label) => !seen.has(label.toLowerCase()));
  const generated = fillers.map((label, index) => ({
    label,
    count: Math.max(1, Math.round(product.current.complaints * (0.075 - index * 0.004))),
  }));
  return [...product.themes, ...generated]
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, 10);
}

function buildReviews(product: Product, problem: Problem): Review[] {
  return SOURCE_ORDER.flatMap((source, sourceIndex) => {
    const page = source === "app"
      ? "Guardian App reviews"
      : source === "marketplace"
        ? "Marketplace product page"
        : source === "service"
          ? "Customer service conversation"
          : "Social / community post";
    const sourceVolume = product.sources[source];
    const count = sourceVolume > 20 ? 3 : sourceVolume > 5 ? 2 : 1;
    return Array.from({ length: count }, (_, index) => ({
      id: `${product.id}-${problem.label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${source}-${index + 1}`,
      source,
      page,
      timestamp: `2026-07-${String(11 - ((sourceIndex + index) % 3)).padStart(2, "0")} ${String(8 + sourceIndex * 2 + index).padStart(2, "0")}:${index ? "18" : "42"}`,
      problem: problem.label,
      text: index === 0
        ? `Customer reported ${problem.label.toLowerCase()} while using ${product.name}. The record was grouped into this issue from ${SOURCE_LABELS[source]}.`
        : `Follow-up feedback mentions ${problem.label.toLowerCase()} and requests support for ${product.shortName}.`,
    }));
  });
}

// Retained as the formatted tooltip source if this chart later moves to a layout
// with dedicated tooltip space. The compact donut intentionally uses its center.
function ProblemTooltip({ active, payload, total }: ProblemTooltipProps) {
  const problem = payload?.[0]?.payload;
  if (!active || !problem) return null;
  return (
    <div className="problem-pie-tooltip" role="status">
      <strong>{problem.label}</strong>
      <span>{problem.count} mentions · {Math.round((problem.count / total) * 100)}%</span>
    </div>
  );
}

export function ProductProblems({
  product,
  compareMode = false,
  requestedProblem = null,
  onRequestedProblemClose,
}: {
  product: Product;
  compareMode?: boolean;
  requestedProblem?: ProblemReviewSelection | null;
  onRequestedProblemClose?: () => void;
}) {
  const [problemWindow, setProblemWindow] = useState<FeedbackWindow>("72h");
  const scopedProduct = useMemo(
    () => projectProductToWindow(product, problemWindow),
    [problemWindow, product],
  );
  const problems = useMemo(() => buildProblems(scopedProduct), [scopedProduct]);
  const previousProduct = useMemo(
    () => projectProductToPreviousWindow(product, problemWindow),
    [problemWindow, product],
  );
  const previousProblems = useMemo(() => buildProblems(previousProduct), [previousProduct]);
  const previousProblemMap = useMemo(
    () => new Map(previousProblems.map((problem) => [problem.label, problem.count])),
    [previousProblems],
  );
  const problemComparisonData = problems.map((problem) => ({
    label: problem.label,
    current: problem.count,
    previous: previousProblemMap.get(problem.label) ?? 0,
  }));
  const [activeProblem, setActiveProblem] = useState<Problem | null>(null);
  const [hoveredProblem, setHoveredProblem] = useState<Problem | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceKey | "all">("all");
  const [activeReview, setActiveReview] = useState<Review | null>(null);
  const reviews = useMemo(() => activeProblem ? buildReviews(scopedProduct, activeProblem) : [], [activeProblem, scopedProduct]);
  const visibleReviews = sourceFilter === "all" ? reviews : reviews.filter((review) => review.source === sourceFilter);
  const problemTotal = problems.reduce((total, problem) => total + problem.count, 0);
  const pieData = problems.map((problem, index) => ({ ...problem, fill: PROBLEM_COLORS[index], index }));

  useEffect(() => {
    if (!requestedProblem) return;
    setActiveProblem(requestedProblem);
    setActiveReview(null);
    setSourceFilter("all");
  }, [requestedProblem]);

  const close = () => {
    setActiveProblem(null);
    setActiveReview(null);
    setSourceFilter("all");
    onRequestedProblemClose?.();
  };

  const problemActions = (
    <div className="product-problem-legend" aria-label="Top problem legend and actions">
      {problems.map((problem, index) => (
        <button
          type="button"
          key={problem.label}
          onMouseEnter={() => setHoveredProblem(problem)}
          onMouseLeave={() => setHoveredProblem(null)}
          onFocus={() => setHoveredProblem(problem)}
          onBlur={() => setHoveredProblem(null)}
          onClick={() => setActiveProblem(problem)}
          aria-label={`Investigate ${problem.label}`}
        >
          <i style={{ background: PROBLEM_COLORS[index] }} />
          <span><strong>{problem.label}</strong><small>{problem.count} mentions</small></span>
          <em>{Math.round((problem.count / problemTotal) * 100)}%</em>
        </button>
      ))}
    </div>
  );

  return (
    <>
      <section className="product-problems" aria-labelledby="product-problems-title">
        <div className="product-problems__head">
          <div>
            <span className="step-label">Product issue landscape</span>
            <h3 id="product-problems-title">Top 10 problems</h3>
            <p>Number of customer feedback mentions classified into each problem.</p>
          </div>
          <div className="product-problems__controls">
            <TimeRangeSelect
              ariaLabel="Filter top problems by time"
              value={problemWindow}
              options={FEEDBACK_WINDOWS.map((value) => ({ value, label: FEEDBACK_WINDOW_LABELS[value] }))}
              onChange={setProblemWindow}
            />
            {compareMode && <span className="comparison-mode-label">Current vs previous period</span>}
            <span>{product.shortName} · Synthetic demo</span>
          </div>
        </div>
        {!SHOW_LEGACY_PROBLEM_PIE || compareMode ? (
          <>
          <div
            className="product-problem-comparison"
            role="img"
            aria-label={`Top 10 problems measured in customer mentions for ${FEEDBACK_WINDOW_LABELS[problemWindow].toLowerCase()}${compareMode ? " compared with the previous matching period" : " shown as a horizontal bar chart"}`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={problemComparisonData} layout="vertical" margin={{ top: 14, right: 42, bottom: 28, left: 12 }} barCategoryGap="22%">
                <CartesianGrid horizontal={false} stroke="var(--border-soft)" />
                <XAxis
                  type="number"
                  allowDecimals={false}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "var(--muted)", fontSize: 9 }}
                  label={{ value: "Customer mentions", position: "insideBottom", offset: -14, fill: "var(--muted)", fontSize: 10 }}
                />
                <YAxis type="category" dataKey="label" width={130} axisLine={false} tickLine={false} tick={{ fill: "var(--text)", fontSize: 9 }} />
                <Tooltip cursor={{ fill: "var(--hover-bg)" }} />
                {compareMode && <Legend iconType="circle" wrapperStyle={{ fontSize: 10, color: "var(--muted)" }} />}
                {compareMode && (
                  <Bar dataKey="previous" name="Previous period" fill="#aeb5ba" radius={[0, 4, 4, 0]}>
                    <LabelList dataKey="previous" position="right" fill="var(--muted)" fontSize={9} />
                  </Bar>
                )}
                <Bar dataKey="current" name="Current period" fill="#e33b36" radius={[0, 4, 4, 0]}>
                  <LabelList dataKey="current" position="right" fill="var(--text)" fontSize={9} fontWeight={700} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          {problemActions}
          </>
        ) : (
        <div className="product-problem-visual">
          <div
            className="product-problem-pie"
            role="img"
            aria-label="Top 10 problems by share of problem mentions. Select a slice to investigate."
            onClick={(event) => {
              const target = (event.target as Element).closest<SVGPathElement>("[data-problem-index]");
              if (!target) return;
              const index = Number(target.dataset.problemIndex);
              if (Number.isInteger(index) && problems[index]) setActiveProblem(problems[index]);
            }}
          >
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="count"
                  nameKey="label"
                  innerRadius={78}
                  outerRadius={128}
                  paddingAngle={2}
                  shape={(props: PieSectorShapeProps) => {
                    const index = props.index;
                    return (
                      <Sector
                        {...props}
                        className="problem-pie-slice"
                        data-problem-index={index}
                        role="button"
                        tabIndex={0}
                        aria-label={`Investigate ${problems[index].label}`}
                        onMouseEnter={() => setHoveredProblem(problems[index])}
                        onMouseLeave={() => setHoveredProblem(null)}
                        onFocus={() => setHoveredProblem(problems[index])}
                        onBlur={() => setHoveredProblem(null)}
                        onClick={() => setActiveProblem(problems[index])}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") setActiveProblem(problems[index]);
                        }}
                      />
                    );
                  }}
                />
                <Tooltip content={() => null} cursor={false} />
              </PieChart>
            </ResponsiveContainer>
            <div className="product-problem-pie__center" aria-live="polite">
              <strong>{hoveredProblem?.count ?? problemTotal}</strong>
              <span>{hoveredProblem?.label ?? "Top 10 mentions"}</span>
              <small>{hoveredProblem ? `${Math.round((hoveredProblem.count / problemTotal) * 100)}% of mentions` : "Click a slice"}</small>
            </div>
          </div>
          {problemActions}
        </div>
        )}
        <p className="data-caveat">Bars rank problem mentions for the selected period; comparison mode adds the previous same-length period. Problems combine seeded themes with deterministic demo taxonomy; production ranking should use classified review-level records.</p>
      </section>

      <MonthlySentimentChart product={product} compareMode={compareMode} />

      {activeProblem && (
        <div className="source-review-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && close()}>
          <section className="source-review-modal" role="dialog" aria-modal="true" aria-labelledby="source-review-title">
            <header>
              <div>
                <span className="eyebrow">{product.shortName} · {activeProblem.count} related mentions</span>
                <h2 id="source-review-title">{activeProblem.label}</h2>
                <p>Source pages and review records contributing to this problem.</p>
              </div>
              <button type="button" className="source-review-close" onClick={close} aria-label="Close problem investigation"><X size={20} /></button>
            </header>

            {activeReview ? (
              <article className="source-page-detail">
                <button type="button" onClick={() => setActiveReview(null)}><ArrowLeft size={15} /> Back to all source pages</button>
                <span className="source-page-detail__source">{SOURCE_LABELS[activeReview.source]}</span>
                <h3>{activeReview.page}</h3>
                <dl>
                  <div><dt>Review ID</dt><dd>{activeReview.id}</dd></div>
                  <div><dt>Published</dt><dd>{activeReview.timestamp}</dd></div>
                  <div><dt>Problem</dt><dd>{activeReview.problem}</dd></div>
                  <div><dt>Product</dt><dd>{product.name}</dd></div>
                </dl>
                <blockquote>“{activeReview.text}”</blockquote>
                <p className="data-caveat">Synthetic provenance page. A production record should expose the retained external `sourceUrl` here.</p>
              </article>
            ) : (
              <>
                <nav className="source-review-tabs" aria-label="Filter reviews by source">
                  <button type="button" className={sourceFilter === "all" ? "is-active" : ""} onClick={() => setSourceFilter("all")}>All pages <span>{reviews.length}</span></button>
                  {SOURCE_ORDER.map((source) => (
                    <button type="button" className={sourceFilter === source ? "is-active" : ""} onClick={() => setSourceFilter(source)} key={source}>
                      {SOURCE_LABELS[source]} <span>{reviews.filter((review) => review.source === source).length}</span>
                    </button>
                  ))}
                </nav>
                <div className="source-review-list">
                  {visibleReviews.map((review) => (
                    <article key={review.id}>
                      <div><span>{review.page}</span><time>{review.timestamp}</time></div>
                      <p>“{review.text}”</p>
                      <footer><small>{review.id}</small><button type="button" onClick={() => setActiveReview(review)}>Open source page <ArrowSquareOut size={14} /></button></footer>
                    </article>
                  ))}
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
