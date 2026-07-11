import { useMemo, useState } from "react";
import { ArrowRight, TrendDown, TrendUp } from "@phosphor-icons/react";
import { deriveDashboard, type ProductId } from "../data/dashboard";
import { PortfolioAnalytics, PortfolioSideCharts } from "./PortfolioAnalytics";

type DashboardData = ReturnType<typeof deriveDashboard>;

const REVIEW_PLATFORMS = [
  { id: "all", label: "All platforms", reviewShare: 1, negativeDelta: 0, trendDelta: 0 },
  { id: "facebook", label: "Facebook", reviewShare: 0.34, negativeDelta: 2, trendDelta: -2 },
  { id: "tiktok", label: "TikTok", reviewShare: 0.27, negativeDelta: 4, trendDelta: -3 },
  { id: "instagram", label: "Instagram", reviewShare: 0.23, negativeDelta: -1, trendDelta: 1 },
  { id: "youtube", label: "YouTube", reviewShare: 0.16, negativeDelta: -2, trendDelta: 2 },
] as const;

type ReviewPlatformId = (typeof REVIEW_PLATFORMS)[number]["id"];

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function sentimentMix(
  product: DashboardData["selectedProducts"][number],
  negativeDelta = 0,
) {
  const negative = clamp(
    Math.round(8 + (4.7 - product.rating) * 18 - product.sentimentDelta * 0.25 + negativeDelta),
    4,
    38,
  );
  const neutral = clamp(Math.round(13 + (4.5 - product.rating) * 5), 10, 18);
  return { positive: 100 - negative - neutral, neutral, negative };
}

function experienceMix(complaints: number, reviews: number, neutral = 15) {
  const complaintRate = reviews ? (complaints / reviews) * 100 : 0;
  const negative = clamp(Math.round(8 + complaintRate * 1.7), 8, 28);
  return { positive: 100 - neutral - negative, neutral, negative };
}

function ExperienceSignalBenchmark({ data }: { data: DashboardData }) {
  const peers = Object.fromEntries(data.competitors.map((competitor) => [competitor.retailer, competitor]));
  const guardianMix = experienceMix(data.currentComplaints, data.currentReviews);
  const watsons = peers.watsons;
  const hasaki = peers.hasaki;
  const benchmarkRows = [
    {
      brand: "Guardian",
      mix: guardianMix,
      reviews: data.currentReviews,
      signal: "Delivery experience",
      isGuardian: true,
    },
    {
      brand: "Watsons",
      mix: experienceMix(watsons?.complaints ?? 0, watsons?.reviews ?? 0, 16),
      reviews: watsons?.reviews ?? 0,
      signal: "Customer service",
      isGuardian: false,
    },
    {
      brand: "Hasaki",
      mix: experienceMix(hasaki?.complaints ?? 0, hasaki?.reviews ?? 0),
      reviews: hasaki?.reviews ?? 0,
      signal: "Promotions & pricing",
      isGuardian: false,
    },
  ];
  const peerNegative = benchmarkRows
    .filter((row) => !row.isGuardian)
    .reduce((total, row) => total + row.mix.negative, 0) / 2;
  const gap = guardianMix.negative - peerNegative;

  return (
    <section className="experience-benchmark" aria-labelledby="experience-benchmark-title">
      <div className="experience-benchmark__head">
        <div>
          <span className="eyebrow">Comparable public feedback</span>
          <h3 id="experience-benchmark-title">Experience signal benchmark</h3>
          <p>Brand-level experience tone, excluding Guardian-only internal service signals.</p>
        </div>
        <span className="benchmark-confidence">Directional signal</span>
      </div>

      <div className="experience-benchmark__insight">
        <strong>Guardian has {Math.abs(gap).toFixed(1)}pp {gap >= 0 ? "more" : "less"} negative experience feedback than peers.</strong>
        <span>Delivery is the largest observable Guardian experience gap in this synthetic sample.</span>
      </div>

      <div className="experience-benchmark__table" role="table" aria-label="Experience sentiment benchmark for Guardian, Watsons and Hasaki">
        <div className="experience-benchmark__table-head" role="row">
          <span>Brand</span><span>Experience tone</span><span>Negative</span><span>Comparable sample</span><span>Leading signal</span>
        </div>
        {benchmarkRows.map((row) => (
          <div className={`experience-benchmark__row ${row.isGuardian ? "is-guardian" : ""}`} role="row" key={row.brand}>
            <strong>{row.brand}</strong>
            <span className="tone-bar" aria-label={`${row.mix.positive}% positive, ${row.mix.neutral}% neutral, ${row.mix.negative}% negative`}>
              <i className="tone-bar__positive" style={{ width: `${row.mix.positive}%` }} />
              <i className="tone-bar__neutral" style={{ width: `${row.mix.neutral}%` }} />
              <i className="tone-bar__negative" style={{ width: `${row.mix.negative}%` }} />
            </span>
            <strong className="experience-benchmark__negative">{row.mix.negative}%</strong>
            <span>{row.reviews.toLocaleString("en-US")} reviews</span>
            <span className="experience-benchmark__signal">{row.signal}</span>
          </div>
        ))}
      </div>

      <p className="data-caveat">Synthetic comparable public-review sample · Last 90 days. Treat as directional until source matching, deduplication and experience classification are connected.</p>
    </section>
  );
}

export function PortfolioOverview({
  data,
  onSelectProduct,
  onInvestigateProduct,
}: {
  data: DashboardData;
  onSelectProduct: (id: ProductId) => void;
  onInvestigateProduct: (id: ProductId) => void;
}) {
  const [platformId, setPlatformId] = useState<ReviewPlatformId>("all");
  const platform = REVIEW_PLATFORMS.find((option) => option.id === platformId) ?? REVIEW_PLATFORMS[0];
  const rows = useMemo(() => data.selectedProducts.map((product) => ({
    product,
    mix: sentimentMix(product, platform.negativeDelta),
    reviewCount: Math.round(product.current.reviews * platform.reviewShare),
    trend: product.sentimentDelta + platform.trendDelta,
    topProblemCount: Math.round((product.themes[0]?.count ?? 0) * platform.reviewShare),
  })), [data.selectedProducts, platform]);
  const platformReviewCount = rows.reduce((total, row) => total + row.reviewCount, 0);
  const complaintRate = data.currentReviews ? (data.currentComplaints / data.currentReviews) * 100 : 0;
  const aboveBaseline = data.selectedProducts.filter((product) => {
    const current = product.current.reviews ? product.current.complaints / product.current.reviews : 0;
    const baseline = product.baseline.reviews ? product.baseline.complaints / product.baseline.reviews : 0;
    return current > baseline;
  }).length;
  const latestActivityDay = data.activities[0]?.timestamp.slice(0, 10);
  const todayActivities = latestActivityDay
    ? data.activities.filter((activity) => activity.timestamp.startsWith(latestActivityDay))
    : [];
  const todaySignalCount = todayActivities.reduce((total, activity) => {
    const change = Number.parseInt(activity.delta.replace(/[^\d-]/g, ""), 10);
    return total + (Number.isNaN(change) || change < 0 ? 0 : change);
  }, 0);
  const todayProductCount = new Set(todayActivities.map((activity) => activity.productId)).size;
  const firstActivityTime = todayActivities.at(-1)?.timeLabel;
  return (
    <div className="portfolio-overview">
      <section className="portfolio-health" aria-labelledby="portfolio-health-title">
        <div className="portfolio-health__head">
          <div>
            <span className="eyebrow">Today&apos;s portfolio brief</span>
            <h2 id="portfolio-health-title">Leakage is today&apos;s priority</h2>
            <p><strong>{todaySignalCount} new matching signals</strong> since {firstActivityTime} across {todayProductCount} sunscreen products.</p>
          </div>
          <div className="portfolio-health__meta">
            <span className="portfolio-scope-label">Viewing · All {data.selectedProducts.length} products</span>
            <span className="derived-label">Synthetic demo data</span>
          </div>
        </div>

        <div className="portfolio-scan-strip" aria-label="All product portfolio metrics">
          <div className="portfolio-scan-stat portfolio-scan-stat--critical"><span>New signals today</span><strong>{todaySignalCount}</strong><small>Latest activity at {data.activities[0]?.timeLabel}</small></div>
          <div className="portfolio-scan-stat"><span>Products involved</span><strong>{todayProductCount}</strong><small>SunShield + UV Defense</small></div>
          <div className="portfolio-scan-stat portfolio-scan-stat--critical"><span>Above baseline</span><strong>{aboveBaseline}</strong><small>72h vs 28-day norm</small></div>
          <div className="portfolio-scan-stat"><span>Complaint share</span><strong>{complaintRate.toFixed(1)}%</strong><small>{data.currentComplaints.toLocaleString("en-US")} of {data.currentReviews.toLocaleString("en-US")} reviews · 72h</small></div>
        </div>
      </section>

      <div className="portfolio-overview__grid">
        <div className="portfolio-main-column">
          <section className="portfolio-table-section">
            <div className="portfolio-section-head">
              <div><span className="eyebrow">Complete product view</span><h3>Review tone by product</h3></div>
              <span>Positive · Neutral · Negative</span>
            </div>
            <div className="platform-filter">
              <label htmlFor="review-platform">Platform</label>
              <select
                id="review-platform"
                aria-label="Filter reviews by platform"
                value={platformId}
                onChange={(event) => setPlatformId(event.target.value as ReviewPlatformId)}
              >
                {REVIEW_PLATFORMS.map((option) => (
                  <option value={option.id} key={option.id}>{option.label}</option>
                ))}
              </select>
              <span aria-live="polite">{platformReviewCount.toLocaleString("en-US")} reviews</span>
            </div>
            <div className="portfolio-table" role="table" aria-label={`Estimated sentiment by product on ${platform.label}`}>
              <div className="portfolio-table__head" role="row">
                <span>Product</span><span>Review tone</span><span>Negative</span><span>Trend</span><span>Top problem</span><span aria-hidden="true" />
              </div>
              {rows.map(({ product, mix: productMix, reviewCount, trend, topProblemCount }) => (
                <div className="portfolio-table__row" role="row" key={product.id}>
                  <button type="button" className="portfolio-product" onClick={() => onSelectProduct(product.id)}>
                    <strong>{product.shortName}</strong><small>{product.category} · {reviewCount} reviews</small>
                  </button>
                  <span className="tone-bar" aria-label={`${productMix.positive}% positive, ${productMix.neutral}% neutral, ${productMix.negative}% negative`}>
                    <i className="tone-bar__positive" style={{ width: `${productMix.positive}%` }} />
                    <i className="tone-bar__neutral" style={{ width: `${productMix.neutral}%` }} />
                    <i className="tone-bar__negative" style={{ width: `${productMix.negative}%` }} />
                  </span>
                  <strong className="portfolio-negative">{productMix.negative}%</strong>
                  <span className={`portfolio-trend ${trend >= 0 ? "is-up" : "is-down"}`}>
                    {trend >= 0 ? <TrendUp size={16} /> : <TrendDown size={16} />}
                    {trend > 0 ? "+" : ""}{trend}pp
                  </span>
                  <span className="portfolio-top-problem"><strong>{product.themes[0]?.label ?? "No dominant issue"}</strong><small>{topProblemCount} mentions</small></span>
                  <button type="button" className="portfolio-investigate" onClick={() => onInvestigateProduct(product.id)} aria-label={`Investigate ${product.shortName}: ${product.themes[0]?.label ?? "no dominant issue"}`}>
                    Investigate <ArrowRight size={14} weight="bold" />
                  </button>
                </div>
              ))}
            </div>
          </section>

          <ExperienceSignalBenchmark data={data} />
        </div>

        <PortfolioSideCharts data={data} />
      </div>

      <PortfolioAnalytics data={data} />
    </div>
  );
}
