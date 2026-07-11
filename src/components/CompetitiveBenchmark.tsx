import { useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  Info,
  Lightbulb,
  TrendUp,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatPercent, type ProductId, type deriveDashboard } from "../data/dashboard";
import { ProductProblems, type ProblemReviewSelection } from "./ProductProblems";

type DashboardData = ReturnType<typeof deriveDashboard>;

const BRAND_COLORS = {
  Guardian: "#f67e2a",
  Hasaki: "#197b8a",
  Watsons: "#7650a0",
} as const;

const MIN_SEGMENT_SAMPLE = 30;
const MIN_COHORT_COVERAGE = 0.6;

const TOOLTIP_STYLE = {
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--surface)",
  color: "var(--text)",
  fontSize: 11,
};

function rate(complaints: number, reviews: number) {
  return reviews ? (complaints / reviews) * 100 : 0;
}

function round(value: number, digits = 1) {
  return Number(value.toFixed(digits));
}

function clamp(value: number, min = 0, max = 100) {
  return Math.min(max, Math.max(min, value));
}

function BenchmarkCardHeader({
  eyebrow,
  title,
  meta,
  onViewComments,
}: {
  eyebrow: string;
  title: string;
  meta: string;
  onViewComments?: () => void;
}) {
  return (
    <header className="benchmark-card__head">
      <div><span>{eyebrow}</span><h2>{title}</h2></div>
      <div className="benchmark-card__actions">
        <small>{meta}</small>
        {onViewComments && <button type="button" onClick={onViewComments} aria-label={`View related comments for ${title}`}>View comments</button>}
      </div>
    </header>
  );
}

type BenchmarkReviewTarget = {
  product: DashboardData["selectedProducts"][number];
  problem: ProblemReviewSelection;
};

export function CompetitiveBenchmark({
  data,
  onInvestigateProduct,
}: {
  data: DashboardData;
  onInvestigateProduct: (id: ProductId) => void;
}) {
  const [reviewTarget, setReviewTarget] = useState<BenchmarkReviewTarget | null>(null);
  const benchmark = useMemo(() => {
    const comparableProducts = data.selectedProducts.filter((product) =>
      product.current.reviews >= MIN_SEGMENT_SAMPLE &&
      product.competitors.hasaki.reviews >= MIN_SEGMENT_SAMPLE &&
      product.competitors.watsons.reviews >= MIN_SEGMENT_SAMPLE,
    );
    const guardianComparableReviews = comparableProducts.reduce(
      (total, product) => total + product.current.reviews,
      0,
    );
    const hasakiComparableReviews = comparableProducts.reduce(
      (total, product) => total + product.competitors.hasaki.reviews,
      0,
    );
    const watsonsComparableReviews = comparableProducts.reduce(
      (total, product) => total + product.competitors.watsons.reviews,
      0,
    );
    const referenceN = Math.min(
      guardianComparableReviews,
      hasakiComparableReviews,
      watsonsComparableReviews,
    );
    const coverage = data.currentReviews
      ? guardianComparableReviews / data.currentReviews
      : 0;
    const standardizedRate = (brand: "guardian" | "hasaki" | "watsons") => {
      if (!guardianComparableReviews) return 0;
      return comparableProducts.reduce((total, product) => {
        const guardianWeight = product.current.reviews / guardianComparableReviews;
        const sample = brand === "guardian" ? product.current : product.competitors[brand];
        return total + guardianWeight * rate(sample.complaints, sample.reviews);
      }, 0);
    };
    const marginOfError = (standardizedComplaintRate: number) => {
      if (!referenceN) return null;
      const proportion = standardizedComplaintRate / 100;
      return round(1.96 * Math.sqrt((proportion * (1 - proportion)) / referenceN) * 100);
    };
    const guardianRate = standardizedRate("guardian");
    const hasakiRate = standardizedRate("hasaki");
    const watsonsRate = standardizedRate("watsons");
    const hasakiRaw = data.competitors.find((peer) => peer.retailer === "hasaki");
    const watsonsRaw = data.competitors.find((peer) => peer.retailer === "watsons");
    const brandRates = [
      {
        brand: "Guardian",
        rate: round(guardianRate),
        rawRate: round(rate(data.currentComplaints, data.currentReviews)),
        complaints: data.currentComplaints,
        reviews: data.currentReviews,
        margin: marginOfError(guardianRate),
      },
      {
        brand: "Hasaki",
        rate: round(hasakiRate),
        rawRate: round(rate(hasakiRaw?.complaints ?? 0, hasakiRaw?.reviews ?? 0)),
        complaints: hasakiRaw?.complaints ?? 0,
        reviews: hasakiRaw?.reviews ?? 0,
        margin: marginOfError(hasakiRate),
      },
      {
        brand: "Watsons",
        rate: round(watsonsRate),
        rawRate: round(rate(watsonsRaw?.complaints ?? 0, watsonsRaw?.reviews ?? 0)),
        complaints: watsonsRaw?.complaints ?? 0,
        reviews: watsonsRaw?.reviews ?? 0,
        margin: marginOfError(watsonsRate),
      },
    ];

    const comparableThemeCounts = new Map<string, number>();
    comparableProducts.forEach((product) => {
      product.themes.forEach((theme) => {
        comparableThemeCounts.set(theme.label, (comparableThemeCounts.get(theme.label) ?? 0) + theme.count);
      });
    });
    const comparableThemes = [...comparableThemeCounts.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
    const topics = comparableThemes.slice(0, 6).map((theme, index) => {
      const guardian = rate(theme.count, guardianComparableReviews);
      const hasakiFactor = [0.45, 0.6, 0.78, 1.08, 0.9, 1.04][index] ?? 0.92;
      const watsonsFactor = [0.54, 0.68, 0.74, 0.94, 1.12, 0.86][index] ?? 0.96;
      const hasaki = guardian * hasakiFactor;
      const watsons = guardian * watsonsFactor;
      return {
        topic: theme.label,
        Guardian: round(guardian),
        Hasaki: round(hasaki),
        Watsons: round(watsons),
        gap: round(guardian - Math.min(hasaki, watsons)),
        mentions: theme.count,
      };
    });

    const trendMultipliers = [0.58, 0.62, 0.68, 0.73, 0.81, 0.9, 0.96, 1];
    const labels = ["04 Jul", "05 Jul", "06 Jul", "07 Jul", "08 Jul", "09 Jul", "10 Jul", "11 Jul"];
    const trend = labels.map((date, index) => ({
      date,
      Guardian: round(guardianRate * trendMultipliers[index]),
      Hasaki: round(hasakiRate * (0.94 + index * 0.009)),
      Watsons: round(watsonsRate * (1.03 - index * 0.006)),
    }));

    const averageGuardianRating = comparableProducts.reduce(
      (total, product) => total + product.rating * product.current.reviews,
      0,
    ) / Math.max(1, guardianComparableReviews);
    const experienceProfile = [
      {
        metric: "Complaint control",
        Guardian: round(clamp(100 - guardianRate * 5), 0),
        Hasaki: round(clamp(100 - hasakiRate * 5), 0),
        Watsons: round(clamp(100 - watsonsRate * 5), 0),
      },
      { metric: "Average rating", Guardian: round(averageGuardianRating * 20, 0), Hasaki: 91, Watsons: 89 },
      { metric: "Recommendation", Guardian: 72, Hasaki: 81, Watsons: 78 },
      { metric: "Resolution", Guardian: 68, Hasaki: 76, Watsons: 80 },
      { metric: "Issue stability", Guardian: round(clamp(104 - (data.velocity ?? 1) * 24), 0), Hasaki: 82, Watsons: 79 },
    ];

    const peers = brandRates.filter((brand) => brand.brand !== "Guardian");
    const bestPeer = [...peers].sort((a, b) => a.rate - b.rate)[0];
    const worstProduct = [...comparableProducts].sort(
      (a, b) => rate(b.current.complaints, b.current.reviews) - rate(a.current.complaints, a.current.reviews),
    )[0];

    const rankable = coverage >= MIN_COHORT_COVERAGE && referenceN >= MIN_SEGMENT_SAMPLE;

    return {
      brandRates,
      topics,
      trend,
      experienceProfile,
      bestPeer,
      worstProduct,
      comparableProducts,
      referenceN,
      coverage,
      rankable,
    };
  }, [data]);

  const leadingTopic = benchmark.topics[0];
  const guardianRate = benchmark.brandRates[0]?.rate ?? 0;
  const peerGap = round(guardianRate - (benchmark.bestPeer?.rate ?? 0));
  const enoughSamples = benchmark.rankable;
  const openComments = (topicLabel?: string) => {
    const label = topicLabel ?? leadingTopic?.topic;
    if (!label) return;
    const matchingProduct = [...benchmark.comparableProducts]
      .filter((product) => product.themes.some((theme) => theme.label === label))
      .sort((a, b) => {
        const aCount = a.themes.find((theme) => theme.label === label)?.count ?? 0;
        const bCount = b.themes.find((theme) => theme.label === label)?.count ?? 0;
        return bCount - aCount;
      })[0] ?? benchmark.worstProduct;
    if (!matchingProduct) return;
    const count = matchingProduct.themes.find((theme) => theme.label === label)?.count
      ?? leadingTopic?.mentions
      ?? 1;
    setReviewTarget({ product: matchingProduct, problem: { label, count } });
  };

  return (
    <div className="benchmark-page">
      <section className="benchmark-hero" aria-labelledby="benchmark-page-title">
        <div>
          <span className="eyebrow">Competitive intelligence</span>
          <h1 id="benchmark-page-title">Competitive Benchmark</h1>
          <p>See where Guardian is winning or losing across comparable customer-experience signals.</p>
        </div>
        <div className="benchmark-cohort" aria-label="Active comparison cohort">
          <span>Last 72 hours</span>
          <span>{data.scopeLabel}</span>
          <span>All feedback channels</span>
          <span>Vietnam</span>
          <strong>Standardized to Guardian product mix</strong>
        </div>
      </section>

      <section className="cohort-quality" aria-labelledby="cohort-quality-title">
        <div className="cohort-quality__summary">
          <span className="eyebrow">Cohort quality</span>
          <h2 id="cohort-quality-title">{benchmark.rankable ? "Comparable with standardization" : "Insufficient comparable coverage"}</h2>
          <p>Raw samples may differ. Rates are reweighted to Guardian&apos;s product mix using only segments available for all three brands.</p>
        </div>
        <div className="cohort-quality__metrics">
          <div><span>Common segments</span><strong>{benchmark.comparableProducts.length}/{data.selectedProducts.length}</strong><small>minimum {MIN_SEGMENT_SAMPLE} reviews per brand</small></div>
          <div><span>Reference n</span><strong>{benchmark.referenceN.toLocaleString("en-US")}</strong><small>same comparison basis for every brand</small></div>
          <div><span>Coverage</span><strong>{Math.round(benchmark.coverage * 100)}%</strong><small>of Guardian&apos;s selected cohort</small></div>
          <div><span>Method</span><strong>Reweighted</strong><small>Guardian product distribution</small></div>
        </div>
      </section>

      <div className="benchmark-layout">
        <div className="benchmark-main">
          <section className="benchmark-card benchmark-card--wide">
            <BenchmarkCardHeader eyebrow="Overall position" title="Standardized complaint rate" meta={`Reference n = ${benchmark.referenceN.toLocaleString("en-US")}`} onViewComments={() => openComments()} />
            <p className="benchmark-card__question">Is Guardian&apos;s customer experience healthier than its marketplace peers?</p>
            <div className="benchmark-chart benchmark-chart--brand benchmark-chart--clickable" role="img" aria-label="Complaint rate comparison between Guardian, Hasaki and Watsons" onClick={() => openComments()}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={benchmark.brandRates} margin={{ top: 22, right: 22, bottom: 4, left: -8 }}>
                  <CartesianGrid vertical={false} stroke="var(--border-soft)" />
                  <XAxis dataKey="brand" axisLine={false} tickLine={false} tick={{ fill: "var(--body-copy)", fontSize: 11 }} />
                  <YAxis unit="%" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value) => [`${value}%`, "Standardized rate"]} />
                  <Bar dataKey="rate" radius={[6, 6, 0, 0]} barSize={58}>
                    {benchmark.brandRates.map((item) => <Cell key={item.brand} fill={BRAND_COLORS[item.brand as keyof typeof BRAND_COLORS]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="benchmark-sample-row">
              {benchmark.brandRates.map((brand) => (
                <button type="button" key={brand.brand} onClick={() => openComments()} aria-label={`View comments related to ${brand.brand} benchmark`}>
                  <strong>{brand.brand}</strong>
                  <span>Raw n {brand.reviews.toLocaleString("en-US")} · raw {brand.rawRate.toFixed(1)}%</span>
                  <small>Standardized {brand.rate.toFixed(1)}% {brand.margin === null ? "" : `±${brand.margin.toFixed(1)}pp`}</small>
                </button>
              ))}
            </div>
            <p className="benchmark-card__footnote">Comment drill-downs show Guardian evidence behind the comparison. Peer row-level comments are not connected in this demo.</p>
          </section>

          <section className="benchmark-card benchmark-card--wide">
            <BenchmarkCardHeader eyebrow="Movement" title="Competitive gap over time" meta="Daily complaint rate" onViewComments={() => openComments()} />
            <p className="benchmark-card__question">Is the gap a one-day spike or a sustained experience problem?</p>
            <div className="benchmark-chart benchmark-chart--trend benchmark-chart--clickable" role="img" aria-label="Eight day complaint-rate trend for Guardian, Hasaki and Watsons" onClick={() => openComments()}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={benchmark.trend} margin={{ top: 16, right: 18, bottom: 4, left: -6 }}>
                  <CartesianGrid stroke="var(--border-soft)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
                  <YAxis unit="%" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value) => [`${value}%`, "Complaint rate"]} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 10 }} />
                  {(Object.keys(BRAND_COLORS) as Array<keyof typeof BRAND_COLORS>).map((brand) => (
                    <Line key={brand} type="monotone" dataKey={brand} stroke={BRAND_COLORS[brand]} strokeWidth={brand === "Guardian" ? 3 : 2} dot={{ r: brand === "Guardian" ? 3 : 2 }} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="benchmark-card benchmark-card--wide">
            <BenchmarkCardHeader eyebrow="Issue diagnosis" title="Where Guardian wins and loses" meta="Share of comparable reviews" onViewComments={() => openComments()} />
            <p className="benchmark-card__question">Which customer problems create the largest competitive disadvantage?</p>
            <div className="benchmark-chart benchmark-chart--topics" role="img" aria-label="Complaint topic rates for Guardian, Hasaki and Watsons">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={benchmark.topics} layout="vertical" margin={{ top: 8, right: 18, bottom: 4, left: 30 }}>
                  <CartesianGrid horizontal={false} stroke="var(--border-soft)" />
                  <XAxis type="number" unit="%" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
                  <YAxis type="category" dataKey="topic" width={110} axisLine={false} tickLine={false} tick={{ fill: "var(--body-copy)", fontSize: 10 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value) => [`${value}%`, "Topic rate"]} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 10 }} />
                  <Bar dataKey="Guardian" fill={BRAND_COLORS.Guardian} radius={[0, 3, 3, 0]} barSize={7} />
                  <Bar dataKey="Hasaki" fill={BRAND_COLORS.Hasaki} radius={[0, 3, 3, 0]} barSize={7} />
                  <Bar dataKey="Watsons" fill={BRAND_COLORS.Watsons} radius={[0, 3, 3, 0]} barSize={7} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="benchmark-card">
            <BenchmarkCardHeader eyebrow="Experience profile" title="Brand strengths" meta="Indexed 0–100" onViewComments={() => openComments()} />
            <p className="benchmark-card__question">Is the gap concentrated in one issue or visible across the experience?</p>
            <div className="benchmark-chart benchmark-chart--radar benchmark-chart--clickable" role="img" aria-label="Indexed experience profile for Guardian, Hasaki and Watsons" onClick={() => openComments()}>
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={benchmark.experienceProfile} outerRadius="68%">
                  <PolarGrid stroke="var(--border)" />
                  <PolarAngleAxis dataKey="metric" tick={{ fill: "var(--muted)", fontSize: 9 }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Radar name="Guardian" dataKey="Guardian" stroke={BRAND_COLORS.Guardian} fill={BRAND_COLORS.Guardian} fillOpacity={0.12} strokeWidth={2.5} />
                  <Radar name="Hasaki" dataKey="Hasaki" stroke={BRAND_COLORS.Hasaki} fill={BRAND_COLORS.Hasaki} fillOpacity={0.06} />
                  <Radar name="Watsons" dataKey="Watsons" stroke={BRAND_COLORS.Watsons} fill={BRAND_COLORS.Watsons} fillOpacity={0.05} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 10 }} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
            <p className="benchmark-card__footnote">Recommendation and resolution are directional demo estimates until post-service feedback is connected.</p>
          </section>

          <section className="benchmark-card benchmark-card--decision">
            <BenchmarkCardHeader eyebrow="Decision table" title="Prioritized experience gaps" meta="Largest gap first" onViewComments={() => openComments()} />
            <div className="benchmark-gap-table" role="table" aria-label="Prioritized competitive experience gaps">
              <div className="benchmark-gap-table__head" role="row"><span>Issue</span><span>Guardian</span><span>Best peer</span><span>Gap</span></div>
              {benchmark.topics.slice(0, 5).map((topic) => {
                const bestPeerRate = Math.min(topic.Hasaki, topic.Watsons);
                return (
                  <div className="benchmark-gap-table__row" role="row" key={topic.topic}>
                    <button type="button" onClick={() => openComments(topic.topic)} aria-label={`View comments related to ${topic.topic}`}>{topic.topic}</button>
                    <span>{formatPercent(topic.Guardian)}</span>
                    <span>{formatPercent(bestPeerRate)}</span>
                    <strong className={topic.gap > 0 ? "is-negative" : "is-positive"}>{topic.gap > 0 ? "+" : ""}{topic.gap.toFixed(1)}pp</strong>
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        <aside className="benchmark-insight" aria-labelledby="benchmark-insight-title">
          <div className="benchmark-insight__label"><Lightbulb size={17} weight="fill" /><span>Key insight</span></div>
          <h2 id="benchmark-insight-title">{benchmark.rankable ? "Guardian is losing on packaging reliability." : "The available samples are not comparable enough to rank."}</h2>
          <p>
            {benchmark.rankable ? (
              <>After standardizing the product mix, complaint rate is <strong>{Math.abs(peerGap).toFixed(1)}pp {peerGap >= 0 ? "higher" : "lower"}</strong> than {benchmark.bestPeer?.brand ?? "the best peer"}. The gap has widened throughout the current period.</>
            ) : (
              <>Only <strong>{Math.round(benchmark.coverage * 100)}%</strong> of Guardian&apos;s selected cohort has sufficient peer coverage. Expand collection before using the benchmark for a decision.</>
            )}
          </p>

          <button className="benchmark-insight__signal" type="button" onClick={() => openComments()} aria-label={`View comments related to ${leadingTopic?.topic ?? "the largest benchmark gap"}`}>
            <span>Largest observable gap</span>
            <strong>{leadingTopic?.topic ?? "No dominant issue"}</strong>
            <small>{leadingTopic ? `+${leadingTopic.gap.toFixed(1)}pp vs best peer · ${leadingTopic.mentions} Guardian mentions` : "Not enough topic data"}</small>
          </button>

          <ul className="benchmark-insight__evidence">
            <li><TrendUp size={16} /><span><strong>Sustained movement</strong>Guardian&apos;s rate rose faster than both peers over the last eight observations.</span></li>
            <li><WarningCircle size={16} /><span><strong>Concentrated risk</strong>{benchmark.worstProduct?.shortName ?? "The leading product"} has the highest complaint rate in this cohort.</span></li>
            <li><CheckCircle size={16} /><span><strong>Comparable sample</strong>{enoughSamples ? `${benchmark.referenceN.toLocaleString("en-US")} reviews form the common reference sample with ${Math.round(benchmark.coverage * 100)}% cohort coverage.` : "At least one shared segment is below the minimum sample or coverage threshold."}</span></li>
          </ul>

          {benchmark.worstProduct && benchmark.rankable && (
            <button className="benchmark-insight__action" type="button" onClick={() => onInvestigateProduct(benchmark.worstProduct.id)}>
              Investigate {benchmark.worstProduct.shortName} <ArrowRight size={15} weight="bold" />
            </button>
          )}

          <div className="benchmark-insight__caveat">
            <Info size={15} />
            <span><strong>Directional demo</strong>Overall rates are product-mix standardized. Peer topics, trend, recommendation and resolution remain synthetic estimates until row-level source provenance, deduplication and matching are connected.</span>
          </div>
        </aside>
      </div>
      {reviewTarget && (
        <div className="benchmark-review-host">
          <ProductProblems
            product={reviewTarget.product}
            requestedProblem={reviewTarget.problem}
            onRequestedProblemClose={() => setReviewTarget(null)}
          />
        </div>
      )}
    </div>
  );
}
