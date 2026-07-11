import { useMemo, useState } from "react";
import { ArrowLeft, ArrowSquareOut, X } from "@phosphor-icons/react";
import { Pie, PieChart, ResponsiveContainer, Sector, Tooltip } from "recharts";
import type { PieSectorShapeProps } from "recharts";
import { SOURCE_LABELS, type Product, type SourceKey } from "../data/dashboard";

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

type Problem = { label: string; count: number };
type Review = {
  id: string;
  source: SourceKey;
  page: string;
  timestamp: string;
  text: string;
  problem: string;
};

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

export function ProductProblems({ product }: { product: Product }) {
  const problems = useMemo(() => buildProblems(product), [product]);
  const [activeProblem, setActiveProblem] = useState<Problem | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceKey | "all">("all");
  const [activeReview, setActiveReview] = useState<Review | null>(null);
  const reviews = useMemo(() => activeProblem ? buildReviews(product, activeProblem) : [], [activeProblem, product]);
  const visibleReviews = sourceFilter === "all" ? reviews : reviews.filter((review) => review.source === sourceFilter);
  const problemTotal = problems.reduce((total, problem) => total + problem.count, 0);
  const pieData = problems.map((problem, index) => ({ ...problem, fill: PROBLEM_COLORS[index], index }));

  const close = () => {
    setActiveProblem(null);
    setActiveReview(null);
    setSourceFilter("all");
  };

  return (
    <>
      <section className="product-problems" aria-labelledby="product-problems-title">
        <div className="product-problems__head">
          <div><span className="step-label">Product issue landscape</span><h3 id="product-problems-title">Top 10 problems</h3></div>
          <span>{product.shortName} · Synthetic demo</span>
        </div>
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
                        onClick={() => setActiveProblem(problems[index])}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") setActiveProblem(problems[index]);
                        }}
                      />
                    );
                  }}
                />
                <Tooltip formatter={(value, _name, item) => [`${value} mentions`, item.payload.label]} />
              </PieChart>
            </ResponsiveContainer>
            <div className="product-problem-pie__center"><strong>{problemTotal}</strong><span>Top 10 mentions</span><small>Click a slice</small></div>
          </div>
          <div className="product-problem-legend" aria-label="Top problem legend and actions">
            {problems.map((problem, index) => (
              <button type="button" key={problem.label} onClick={() => setActiveProblem(problem)} aria-label={`Investigate ${problem.label}`}>
                <i style={{ background: PROBLEM_COLORS[index] }} />
                <span><strong>{problem.label}</strong><small>{problem.count} mentions</small></span>
                <em>{Math.round((problem.count / problemTotal) * 100)}%</em>
              </button>
            ))}
          </div>
        </div>
        <p className="data-caveat">Slice share is normalized across Top 10 problem mentions. Problems combine seeded themes with deterministic demo taxonomy; production ranking should use classified review-level records.</p>
      </section>

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
