import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { deriveDashboard } from "../data/dashboard";

type DashboardData = ReturnType<typeof deriveDashboard>;

const PALETTE = ["#d93431", "#f67e2a", "#7650a0", "#197b8a", "#8b9166"];
const TOOLTIP_STYLE = {
  border: "1px solid #d9dcdf",
  borderRadius: 7,
  background: "#ffffff",
  color: "#171918",
  fontSize: 11,
};

function rate(complaints: number, reviews: number) {
  return reviews ? (complaints / reviews) * 100 : 0;
}

function ChartHeader({ eyebrow, title, meta }: { eyebrow: string; title: string; meta: string }) {
  return (
    <header className="portfolio-chart-card__head">
      <div><span>{eyebrow}</span><h3>{title}</h3></div>
      <small>{meta}</small>
    </header>
  );
}

export function PortfolioSideCharts({ data }: { data: DashboardData }) {
  const [activeThemeIndex, setActiveThemeIndex] = useState(0);
  const themeMix = useMemo(() => {
    const top = data.themes.slice(0, 4);
    const other = data.themes.slice(4).reduce((total, theme) => total + theme.count, 0);
    return other ? [...top, { label: "Other", count: other }] : top;
  }, [data.themes]);

  const channelMix = useMemo(
    () => data.sourceCounts.map((source) => ({
      channel: source.label.replace("Customer service", "Service").replace("Social / community", "Social"),
      mentions: source.count,
    })),
    [data.sourceCounts],
  );

  const totalThemes = themeMix.reduce((total, theme) => total + theme.count, 0);
  const totalChannels = channelMix.reduce((total, channel) => total + channel.mentions, 0);
  const activeTheme = themeMix[activeThemeIndex] ?? themeMix[0];

  return (
    <aside className="portfolio-side portfolio-side--charts">
      <section className="portfolio-chart-card portfolio-chart-card--compact">
        <ChartHeader eyebrow="Complaint mix" title="Top issue themes" meta={`${totalThemes} mentions`} />
        <p className="portfolio-chart-card__question">What are customers complaining about?</p>
        <div className="portfolio-chart portfolio-chart--donut" role="img" aria-label="Donut chart showing top complaint themes across all products">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={themeMix}
                dataKey="count"
                nameKey="label"
                innerRadius={43}
                outerRadius={67}
                paddingAngle={2}
                onMouseEnter={(_, index) => setActiveThemeIndex(index)}
                onMouseLeave={() => setActiveThemeIndex(0)}
              >
                {themeMix.map((theme, index) => (
                  <Cell
                    key={theme.label}
                    fill={PALETTE[index % PALETTE.length]}
                    tabIndex={0}
                    onFocus={() => setActiveThemeIndex(index)}
                    onBlur={() => setActiveThemeIndex(0)}
                  />
                ))}
              </Pie>
              <Tooltip content={() => null} cursor={false} />
            </PieChart>
          </ResponsiveContainer>
          <div className="portfolio-donut-label" aria-live="polite"><strong>{activeTheme?.count ?? 0}</strong><span>{activeTheme?.label ?? "No issue"}</span></div>
        </div>
        <div className="portfolio-chart-legend">
          {themeMix.map((theme, index) => <span key={theme.label}><i style={{ background: PALETTE[index % PALETTE.length] }} />{theme.label}</span>)}
        </div>
      </section>

      <section className="portfolio-chart-card portfolio-chart-card--compact">
        <ChartHeader eyebrow="Source coverage" title="Mentions by channel" meta={`${totalChannels} signals`} />
        <p className="portfolio-chart-card__question">Where are the signals coming from?</p>
        <div className="portfolio-chart portfolio-chart--channel" role="img" aria-label="Bar chart showing complaint mentions by feedback channel">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={channelMix} margin={{ top: 16, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid vertical={false} stroke="var(--border-soft)" />
              <XAxis dataKey="channel" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
              <YAxis axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value) => [value, "Mentions"]} />
              <Bar dataKey="mentions" fill="#197b8a" radius={[4, 4, 0, 0]} barSize={25}>
                <LabelList dataKey="mentions" position="top" style={{ fill: "var(--body-copy)", fontSize: 9, fontWeight: 700 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </aside>
  );
}

export function PortfolioAnalytics({ data }: { data: DashboardData }) {
  const productRates = useMemo(
    () => data.affectedProducts.slice(0, 8).map((product) => ({
      name: product.shortName,
      current: Number(rate(product.current.complaints, product.current.reviews).toFixed(1)),
      baseline: Number(rate(product.baseline.complaints, product.baseline.reviews).toFixed(1)),
      complaints: product.current.complaints,
    })),
    [data.affectedProducts],
  );

  const ratingRelationship = useMemo(
    () => data.selectedProducts.map((product) => ({
      product: product.shortName,
      code: product.sku.replace("GDN-", ""),
      rating: product.rating,
      complaintRate: Number(rate(product.current.complaints, product.current.reviews).toFixed(1)),
      reviewVolume: product.ratingCount,
    })),
    [data.selectedProducts],
  );

  const benchmark = useMemo(() => [
    { name: "Guardian", rate: Number(rate(data.currentComplaints, data.currentReviews).toFixed(1)) },
    ...data.competitors.map((competitor) => ({
      name: competitor.retailer === "hasaki" ? "Hasaki" : "Watsons",
      rate: Number((competitor.share ?? 0).toFixed(1)),
    })),
  ], [data.competitors, data.currentComplaints, data.currentReviews]);

  return (
    <section className="portfolio-analytics" aria-labelledby="portfolio-analytics-title">
      <header className="portfolio-analytics__head">
        <div><span className="eyebrow">Portfolio analysis</span><h2 id="portfolio-analytics-title">Signals across all products</h2></div>
        <span>Current 72-hour window · Synthetic demo data</span>
      </header>

      <div className="portfolio-analytics__grid">
        <article className="portfolio-chart-card">
          <ChartHeader eyebrow="Priority ranking" title="Complaint rate by product" meta="Top 8 products" />
          <p className="portfolio-chart-card__question">Which SKUs need attention first?</p>
          <div className="portfolio-chart portfolio-chart--rank" role="img" aria-label="Horizontal bar chart ranking products by current complaint rate">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={productRates} layout="vertical" margin={{ top: 4, right: 42, bottom: 0, left: 22 }}>
                <CartesianGrid horizontal={false} stroke="var(--border-soft)" />
                <XAxis type="number" unit="%" domain={[0, "dataMax + 3"]} axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                <YAxis type="category" dataKey="name" width={135} axisLine={false} tickLine={false} tick={{ fill: "var(--body-copy)", fontSize: 10 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value) => [`${value}%`, "Complaint rate"]} />
                <Bar dataKey="current" fill="#d93431" radius={[0, 4, 4, 0]} barSize={14}>
                  <LabelList dataKey="current" position="right" formatter={(value) => `${value ?? 0}%`} style={{ fill: "var(--body-copy)", fontSize: 9, fontWeight: 700 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="portfolio-chart-card">
          <ChartHeader eyebrow="Change vs norm" title="Current vs 28-day baseline" meta="Complaint rate" />
          <p className="portfolio-chart-card__question">Which products are moving outside their normal range?</p>
          <div className="portfolio-chart portfolio-chart--rank" role="img" aria-label="Grouped horizontal bar chart comparing current complaint rate with the 28-day baseline">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={productRates} layout="vertical" margin={{ top: 4, right: 20, bottom: 0, left: 22 }}>
                <CartesianGrid horizontal={false} stroke="var(--border-soft)" />
                <XAxis type="number" unit="%" domain={[0, "dataMax + 3"]} axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                <YAxis type="category" dataKey="name" width={135} axisLine={false} tickLine={false} tick={{ fill: "var(--body-copy)", fontSize: 10 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value, name) => [`${value}%`, name === "current" ? "Current 72h" : "28-day baseline"]} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 10 }} formatter={(value) => value === "current" ? "Current 72h" : "28-day baseline"} />
                <Bar dataKey="current" fill="#d93431" radius={[0, 3, 3, 0]} barSize={7} />
                <Bar dataKey="baseline" fill="#aeb5ba" radius={[0, 3, 3, 0]} barSize={7} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="portfolio-chart-card">
          <ChartHeader eyebrow="Relationship" title="Rating vs complaint rate" meta="Bubble size = rating volume" />
          <p className="portfolio-chart-card__question">Do lower-rated products also produce more complaints?</p>
          <div className="portfolio-chart portfolio-chart--scatter" role="img" aria-label="Scatter chart comparing average rating and complaint rate by product">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 28, right: 22, bottom: 8, left: 0 }}>
                <CartesianGrid stroke="var(--border-soft)" />
                <XAxis type="number" dataKey="rating" name="Average rating" unit="★" domain={[4, 5]} tickCount={6} axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                <YAxis type="number" dataKey="complaintRate" name="Complaint rate" unit="%" domain={[0, "dataMax + 3"]} axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                <ZAxis type="number" dataKey="reviewVolume" range={[70, 270]} name="Rating volume" unit=" ratings" />
                <Tooltip cursor={{ strokeDasharray: "4 4" }} contentStyle={TOOLTIP_STYLE} />
                <Scatter name="Products" data={ratingRelationship} fill="#7650a0" fillOpacity={0.78} stroke="#5d3c80" strokeWidth={1}>
                  <LabelList dataKey="code" position="top" style={{ fill: "var(--body-copy)", fontSize: 8 }} />
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="portfolio-chart-card">
          <ChartHeader eyebrow="Peer context" title="Complaint benchmark" meta="Same synthetic cohort" />
          <p className="portfolio-chart-card__question">How does Guardian compare with marketplace peers?</p>
          <div className="portfolio-chart portfolio-chart--benchmark" role="img" aria-label="Bar chart comparing Guardian complaint rate with marketplace peers">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={benchmark} margin={{ top: 20, right: 18, bottom: 0, left: -10 }}>
                <CartesianGrid vertical={false} stroke="var(--border-soft)" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "var(--body-copy)", fontSize: 10 }} />
                <YAxis unit="%" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value) => [`${value}%`, "Complaint rate"]} />
                <Bar dataKey="rate" radius={[5, 5, 0, 0]} barSize={48}>
                  {benchmark.map((item, index) => <Cell key={item.name} fill={["#f67e2a", "#197b8a", "#7650a0"][index]} />)}
                  <LabelList dataKey="rate" position="top" formatter={(value) => `${value ?? 0}%`} style={{ fill: "var(--body-copy)", fontSize: 10, fontWeight: 700 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
      </div>
    </section>
  );
}
