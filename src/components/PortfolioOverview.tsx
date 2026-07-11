import { ArrowRight, ChatCircleText, TrendDown, TrendUp, WarningCircle } from "@phosphor-icons/react";
import { PRODUCTS, deriveDashboard, type ProductId } from "../data/dashboard";

type DashboardData = ReturnType<typeof deriveDashboard>;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function sentimentMix(product: DashboardData["selectedProducts"][number]) {
  const negative = clamp(Math.round(8 + (4.7 - product.rating) * 18 - product.sentimentDelta * 0.25), 4, 34);
  const neutral = clamp(Math.round(13 + (4.5 - product.rating) * 5), 10, 18);
  return { positive: 100 - negative - neutral, neutral, negative };
}

export function PortfolioOverview({
  data,
  onOpenIncident,
  onSelectProduct,
  onInvestigateProduct,
}: {
  data: DashboardData;
  onOpenIncident: (ids: ProductId[]) => void;
  onSelectProduct: (id: ProductId) => void;
  onInvestigateProduct: (id: ProductId) => void;
}) {
  const rows = data.selectedProducts.map((product) => ({ product, mix: sentimentMix(product) }));
  const reviewTotal = rows.reduce((total, row) => total + row.product.current.reviews, 0);
  const portfolioMix = rows.reduce(
    (total, row) => ({
      positive: total.positive + row.mix.positive * row.product.current.reviews,
      neutral: total.neutral + row.mix.neutral * row.product.current.reviews,
      negative: total.negative + row.mix.negative * row.product.current.reviews,
    }),
    { positive: 0, neutral: 0, negative: 0 },
  );
  const mix = {
    positive: reviewTotal ? portfolioMix.positive / reviewTotal : 0,
    neutral: reviewTotal ? portfolioMix.neutral / reviewTotal : 0,
    negative: reviewTotal ? portfolioMix.negative / reviewTotal : 0,
  };
  const incidentIds: ProductId[] = ["P-UV01", "P-UV02"];
  const incident = deriveDashboard(incidentIds);

  return (
    <div className="portfolio-overview">
      <section className="portfolio-health" aria-labelledby="portfolio-health-title">
        <div className="portfolio-health__head">
          <div>
            <span className="eyebrow">Portfolio review tone · Last 72 hours</span>
            <h2 id="portfolio-health-title">How customers feel across all products</h2>
            <p>{data.currentReviews.toLocaleString("en-US")} review records across {data.selectedProducts.length} products and four feedback channels.</p>
          </div>
          <span className="derived-label">Demo-derived sentiment</span>
        </div>

        <div className="sentiment-summary" aria-label="Estimated portfolio sentiment distribution">
          <div className="sentiment-summary__total"><ChatCircleText size={20} /><strong>{data.currentReviews.toLocaleString("en-US")}</strong><span>reviews in scope</span></div>
          <div className="sentiment-stat sentiment-stat--positive"><strong>{mix.positive.toFixed(0)}%</strong><span>Positive</span><small>portfolio estimate</small></div>
          <div className="sentiment-stat sentiment-stat--neutral"><strong>{mix.neutral.toFixed(0)}%</strong><span>Neutral</span><small>portfolio estimate</small></div>
          <div className="sentiment-stat sentiment-stat--negative"><strong>{mix.negative.toFixed(0)}%</strong><span>Negative</span><small>{data.sentimentDelta?.toFixed(1)}pp tone change</small></div>
        </div>
        <p className="sentiment-method">Sentiment shares are deterministic demo estimates from product rating and sentiment-delta fixtures; replace with classifier counts when ingestion is connected.</p>
      </section>

      <div className="portfolio-overview__grid">
        <section className="portfolio-table-section">
          <div className="portfolio-section-head">
            <div><span className="eyebrow">Complete product view</span><h3>Review tone by product</h3></div>
            <span>Positive · Neutral · Negative</span>
          </div>
          <div className="portfolio-table" role="table" aria-label="Estimated sentiment by product">
            <div className="portfolio-table__head" role="row">
              <span>Product</span><span>Review tone</span><span>Negative</span><span>Trend</span><span>Top problem</span><span aria-hidden="true" />
            </div>
            {rows.map(({ product, mix: productMix }) => (
              <div className="portfolio-table__row" role="row" key={product.id}>
                <button type="button" className="portfolio-product" onClick={() => onSelectProduct(product.id)}>
                  <strong>{product.shortName}</strong><small>{product.category} · {product.current.reviews} reviews</small>
                </button>
                <span className="tone-bar" aria-label={`${productMix.positive}% positive, ${productMix.neutral}% neutral, ${productMix.negative}% negative`}>
                  <i className="tone-bar__positive" style={{ width: `${productMix.positive}%` }} />
                  <i className="tone-bar__neutral" style={{ width: `${productMix.neutral}%` }} />
                  <i className="tone-bar__negative" style={{ width: `${productMix.negative}%` }} />
                </span>
                <strong className="portfolio-negative">{productMix.negative}%</strong>
                <span className={`portfolio-trend ${product.sentimentDelta >= 0 ? "is-up" : "is-down"}`}>
                  {product.sentimentDelta >= 0 ? <TrendUp size={16} /> : <TrendDown size={16} />}
                  {product.sentimentDelta > 0 ? "+" : ""}{product.sentimentDelta}pp
                </span>
                <span className="portfolio-top-problem"><strong>{product.themes[0]?.label ?? "No dominant issue"}</strong><small>{product.themes[0]?.count ?? 0} mentions</small></span>
                <button type="button" className="portfolio-investigate" onClick={() => onInvestigateProduct(product.id)} aria-label={`Investigate ${product.shortName}: ${product.themes[0]?.label ?? "no dominant issue"}`}>
                  Investigate <ArrowRight size={14} weight="bold" />
                </button>
              </div>
            ))}
          </div>
        </section>

        <aside className="portfolio-side">
          <section className="theme-summary">
            <div className="portfolio-section-head"><div><span className="eyebrow">Recurring complaints</span><h3>Top negative themes</h3></div></div>
            <div className="theme-list">
              {data.themes.slice(0, 5).map((theme, index) => (
                <div key={theme.label}><span><i>{String(index + 1).padStart(2, "0")}</i>{theme.label}</span><strong>{theme.count}</strong></div>
              ))}
            </div>
          </section>

          <section className="portfolio-incident">
            <span className="portfolio-incident__label"><WarningCircle size={16} weight="fill" /> Needs attention</span>
            <h3>Leakage complaints spiked across 2 sunscreen products</h3>
            <p>SunShield SPF 50 and UV Defense SPF 50+ account for the active packaging signal.</p>
            <div><strong>{incident.velocity?.toFixed(1)}×</strong><span>above baseline</span><strong>{incident.currentComplaints}/{incident.currentReviews}</strong><span>complaints / reviews</span></div>
            <button type="button" onClick={() => onOpenIncident(incidentIds)}>Investigate incident <ArrowRight size={16} weight="bold" /></button>
          </section>
        </aside>
      </div>
    </div>
  );
}
