import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
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

const PALETTE = ["#f67e2a", "#197b8a", "#7650a0", "#d93431", "#8b9166"];
const TOOLTIP_STYLE = {
  border: "1px solid #d9dcdf",
  borderRadius: 7,
  background: "#ffffff",
  color: "#171918",
  fontSize: 11,
};

function complaintRate(product: DashboardData["selectedProducts"][number]) {
  return product.current.reviews ? (product.current.complaints / product.current.reviews) * 100 : 0;
}

export function DashboardCharts({ data, signalLabel }: { data: DashboardData; signalLabel?: string }) {
  const [activeThemeIndex, setActiveThemeIndex] = useState(0);
  const productRates = useMemo(
    () => data.affectedProducts.slice(0, 7).map((product) => ({
      name: product.shortName,
      rate: Number(complaintRate(product).toFixed(1)),
      complaints: product.current.complaints,
      reviews: product.current.reviews,
    })),
    [data.affectedProducts],
  );

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

  const ratingRelationship = useMemo(
    () => data.selectedProducts.map((product) => ({
      product: product.shortName,
      code: product.sku.replace("GDN-", ""),
      rating: product.rating,
      complaintRate: Number(complaintRate(product).toFixed(1)),
      reviewVolume: product.ratingCount,
    })),
    [data.selectedProducts],
  );

  const themeTotal = themeMix.reduce((total, theme) => total + theme.count, 0);
  const activeTheme = themeMix[activeThemeIndex] ?? themeMix[0];

  return (
    <section className="analytics-section" aria-labelledby="analytics-title">
      <header className="analytics-section__head">
        <div>
          <span className="eyebrow">Explore the data</span>
          <h2 id="analytics-title">Visual signal snapshot</h2>
          <p>Selected product scope · Current 72-hour window · Synthetic demo data</p>
        </div>
        <div className="analytics-section__meta">
          {signalLabel && <strong>{signalLabel}</strong>}
          <span>{data.selectedProducts.length} products · {data.currentReviews.toLocaleString("en-US")} reviews in window</span>
        </div>
      </header>

      <div className="analytics-grid">
        <article className="analytics-card analytics-card--priority">
          <header><div><span>Comparison</span><h3>Complaint rate by product</h3></div><small>Complaints ÷ reviews</small></header>
          <p className="analytics-card__question">Which SKUs need attention first?</p>
          <div className="analytics-chart analytics-chart--rank" role="img" aria-label="Horizontal bar chart ranking products by complaint rate">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={productRates} layout="vertical" margin={{ top: 4, right: 42, bottom: 0, left: 18 }}>
                <CartesianGrid horizontal={false} stroke="var(--border-soft)" />
                <XAxis type="number" unit="%" domain={[0, "dataMax + 3"]} axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                <YAxis type="category" dataKey="name" width={148} axisLine={false} tickLine={false} tick={{ fill: "var(--body-copy)", fontSize: 10 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value, name) => name === "rate" ? [`${value}%`, "Complaint rate"] : [value, name]} />
                <Bar dataKey="rate" fill="#f67e2a" radius={[0, 4, 4, 0]} barSize={15}>
                  <LabelList dataKey="rate" position="right" formatter={(value) => `${value ?? 0}%`} style={{ fill: "var(--body-copy)", fontSize: 10, fontWeight: 600 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="analytics-card">
          <header><div><span>Composition</span><h3>Issue theme mix</h3></div><small>{themeTotal} mentions</small></header>
          <p className="analytics-card__question">What are customers complaining about?</p>
          <div className="analytics-chart analytics-chart--pie" role="img" aria-label="Donut chart showing issue theme composition">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={themeMix}
                  dataKey="count"
                  nameKey="label"
                  innerRadius={50}
                  outerRadius={76}
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
            <div className="analytics-donut-label" aria-live="polite"><strong>{activeTheme?.count ?? 0}</strong><span>{activeTheme?.label ?? "No theme"}</span></div>
          </div>
          <div className="analytics-legend">
            {themeMix.map((theme, index) => <span key={theme.label}><i style={{ background: PALETTE[index % PALETTE.length] }} />{theme.label}</span>)}
          </div>
        </article>

        <article className="analytics-card">
          <header><div><span>Source coverage</span><h3>Mentions by channel</h3></div><small>Not normalized</small></header>
          <p className="analytics-card__question">Where are the signals coming from?</p>
          <div className="analytics-chart" role="img" aria-label="Vertical bar chart showing mention volume by customer channel">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={channelMix} margin={{ top: 12, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid vertical={false} stroke="var(--border-soft)" />
                <XAxis dataKey="channel" axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value) => [value, "Mentions"]} />
                <Bar dataKey="mentions" fill="#197b8a" radius={[4, 4, 0, 0]} barSize={30}>
                  <LabelList dataKey="mentions" position="top" style={{ fill: "var(--body-copy)", fontSize: 10, fontWeight: 600 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="analytics-card analytics-card--wide">
          <header><div><span>Relationship</span><h3>Rating vs complaint rate</h3></div><small>Bubble size = rating volume</small></header>
          <p className="analytics-card__question">Are lower-rated products also producing more complaints?</p>
          {ratingRelationship.length >= 8 ? (
            <div className="analytics-chart analytics-chart--scatter" role="img" aria-label="Scatter chart comparing average product rating with complaint rate">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 28, right: 24, bottom: 12, left: 0 }}>
                  <CartesianGrid stroke="var(--border-soft)" />
                  <XAxis type="number" dataKey="rating" name="Average rating" unit="★" domain={[4, 5]} tickCount={6} axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                  <YAxis type="number" dataKey="complaintRate" name="Complaint rate" unit="%" domain={[0, "dataMax + 3"]} axisLine={false} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 10 }} />
                  <ZAxis type="number" dataKey="reviewVolume" range={[80, 320]} name="Rating volume" unit=" reviews" />
                  <Tooltip cursor={{ strokeDasharray: "4 4" }} contentStyle={TOOLTIP_STYLE} />
                  <Scatter name="Products" data={ratingRelationship} fill="#7650a0" fillOpacity={0.76} stroke="#5d3c80" strokeWidth={1}>
                    <LabelList dataKey="code" position="top" style={{ fill: "var(--body-copy)", fontSize: 8 }} />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="analytics-chart-empty">Select at least 8 products to reveal a reliable portfolio relationship.</div>
          )}
        </article>
      </div>
    </section>
  );
}
