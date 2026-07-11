import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  Clock,
  Cube,
  CursorClick,
  GitBranch,
  Package,
  Pulse,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { deriveDashboard } from "../data/dashboard";

const ForceGraph2D = lazy(() => import("react-force-graph-2d"));
const ForceGraph3D = lazy(() => import("react-force-graph-3d"));

type DashboardData = ReturnType<typeof deriveDashboard>;
type GraphMode = "2d" | "3d";
type NodeKind = "product" | "issue" | "evidence" | "hypothesis" | "action";

const COLORS = {
  yellow: "#f67e2a",
  red: "#ef5a5a",
  cyan: "#45b8c8",
  purple: "#9b72cf",
  green: "#55b878",
  blue: "#5689f5",
  muted: "#788089",
};

const NODE_COLORS: Record<NodeKind, string> = {
  product: COLORS.blue,
  issue: COLORS.red,
  evidence: COLORS.cyan,
  hypothesis: COLORS.purple,
  action: COLORS.green,
};

function buildTrend(data: DashboardData) {
  const current = data.complaintShare ?? 0;
  const baseline = data.baselineShare ?? 0;
  const shape = [0.86, 0.94, 0.9, 1.02, 1.13, 1.28, 1.51, 1.76, 2.14, 2.63, 3.08, 3.4];
  const scale = data.velocity ? data.velocity / 3.4 : 0.55;
  return shape.map((factor, index) => ({
    time: `${index * 6}h`,
    complaintRate: Number(Math.min(current, baseline * factor * scale).toFixed(1)),
    baseline: Number(baseline.toFixed(1)),
  }));
}

function buildGraph(data: DashboardData) {
  const nodes: Array<{ id: string; name: string; kind: NodeKind; value: number; color: string }> = [];
  const links: Array<{ source: string; target: string }> = [];

  data.affectedProducts.forEach((product) => {
    nodes.push({
      id: product.id,
      name: product.shortName,
      kind: "product",
      value: Math.max(5, product.current.complaints),
      color: NODE_COLORS.product,
    });
    product.themes.forEach((theme) => {
      const issueId = `issue-${theme.label}`;
      if (!nodes.some((node) => node.id === issueId)) {
        nodes.push({ id: issueId, name: theme.label, kind: "issue", value: theme.count + 4, color: NODE_COLORS.issue });
      }
      links.push({ source: product.id, target: issueId });
    });
  });

  data.evidence.slice(0, 8).forEach((evidence, index) => {
    nodes.push({
      id: evidence.id,
      name: `${evidence.stance === "support" ? "Supports" : "Contradicts"} · ${Math.round(evidence.confidence * 100)}%`,
      kind: "evidence",
      value: 4 + (8 - index) / 2,
      color: NODE_COLORS.evidence,
    });
    links.push({ source: evidence.productId, target: evidence.id });
  });

  data.hypotheses.slice(0, 3).forEach((hypothesis) => {
    nodes.push({
      id: hypothesis.id,
      name: hypothesis.title,
      kind: "hypothesis",
      value: 10 + hypothesis.confidence * 10,
      color: NODE_COLORS.hypothesis,
    });
    hypothesis.productIds.forEach((productId) => links.push({ source: productId, target: hypothesis.id }));
  });

  if (data.status !== "improving" && data.hypotheses[0]) {
    nodes.push({ id: "next-action", name: "Audit packaging & seal process", kind: "action", value: 12, color: NODE_COLORS.action });
    links.push({ source: data.hypotheses[0].id, target: "next-action" });
  }

  return { nodes, links };
}

export function VisualDashboard({
  data,
  onInvestigate,
  onSelectProduct,
}: {
  data: DashboardData;
  onInvestigate: () => void;
  onSelectProduct: (id: DashboardData["selectedProducts"][number]["id"]) => void;
}) {
  const [graphMode, setGraphMode] = useState<GraphMode>("2d");
  const [nodeFilter, setNodeFilter] = useState<NodeKind | "all">("all");
  const [selectedNode, setSelectedNode] = useState<{ name: string; kind: NodeKind } | null>(null);
  const [activeThemeIndex, setActiveThemeIndex] = useState(0);
  const graphWrapRef = useRef<HTMLDivElement>(null);
  const [graphWidth, setGraphWidth] = useState(980);
  const canRenderCanvas = typeof navigator !== "undefined" && !navigator.userAgent.toLowerCase().includes("jsdom");
  const trend = useMemo(() => buildTrend(data), [data]);
  const graph = useMemo(() => buildGraph(data), [data]);
  const filteredGraph = useMemo(() => {
    const kept = new Set(
      graph.nodes
        .filter((node) => nodeFilter === "all" || node.kind === nodeFilter || node.kind === "product")
        .map((node) => node.id),
    );
    return {
      nodes: graph.nodes.filter((node) => kept.has(node.id)).map((node) => ({ ...node })),
      links: graph.links
        .filter((link) => kept.has(link.source) && kept.has(link.target))
        .map((link) => ({ ...link })),
    };
  }, [graph, nodeFilter]);

  useEffect(() => {
    const element = graphWrapRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const updateWidth = () => setGraphWidth(Math.max(320, element.clientWidth));
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const issueTotal = Math.max(1, data.themes.reduce((sum, theme) => sum + theme.count, 0));
  const issueThemes = data.themes.slice(0, 5);
  const activeTheme = issueThemes[activeThemeIndex] ?? issueThemes[0];
  const maxProductComplaints = Math.max(1, ...data.affectedProducts.map((product) => product.current.complaints));
  const topHypothesis = data.hypotheses[0];
  const shouldAct = data.status === "critical" && Boolean(topHypothesis);

  return (
    <div className="visual-dashboard">
      <section className={`next-step-card next-step-card--${data.status ?? "watch"}`}>
        <div className="next-step-card__status">
          <span><Pulse size={18} weight="bold" /> What to do next</span>
          <strong>{shouldAct ? "High priority" : data.status === "improving" ? "Monitor" : "Needs review"}</strong>
        </div>
        <div className="next-step-card__body">
          <div className="next-step-card__icon">
            {data.status === "improving" ? <CheckCircle size={26} weight="fill" /> : <CursorClick size={26} weight="fill" />}
          </div>
          <div>
            <span className="eyebrow">Recommended action</span>
            <h3>{shouldAct ? "Inspect pump-neck seal and cap fit" : data.status === "improving" ? "Keep this cohort on passive monitoring" : "Collect more independent evidence"}</h3>
            <p>
              {topHypothesis
                ? `${Math.round(topHypothesis.confidence * 100)}% confidence · ${topHypothesis.support} supporting signals across ${data.selectedProducts.length} products.`
                : "The selected cohort does not yet have enough consistent evidence for a defensible root-cause action."}
            </p>
          </div>
        </div>
        <div className="next-step-card__meta">
          <span><Clock size={16} /> Suggested: today</span>
          <span><Package size={16} /> Owner: E-commerce Operations</span>
        </div>
        <button type="button" onClick={onInvestigate} disabled={!topHypothesis}>
          {topHypothesis ? "Start investigation" : "Await more evidence"} <ArrowRight size={17} weight="bold" />
        </button>
      </section>

      <section className="insight-card insight-card--wide">
        <div className="insight-card__head">
          <div><span className="eyebrow">What happened?</span><h3>Complaint rate over time</h3></div>
          <span className="chart-takeaway">Spike crossed baseline at 36h</span>
        </div>
        <div className="chart-frame chart-frame--trend" aria-label="Complaint rate trend chart">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={trend} margin={{ top: 12, right: 12, bottom: 0, left: -18 }}>
              <defs>
                <linearGradient id="complaintFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLORS.red} stopOpacity={0.28} />
                  <stop offset="100%" stopColor={COLORS.red} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="rgba(128,135,142,.18)" />
              <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis unit="%" axisLine={false} tickLine={false} tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#141616", border: "1px solid #333", borderRadius: 8 }} />
              <Line dataKey="baseline" name="28-day baseline" stroke={COLORS.muted} strokeDasharray="5 5" dot={false} strokeWidth={2} />
              <Area dataKey="complaintRate" name="Complaint rate" stroke={COLORS.red} fill="url(#complaintFill)" strokeWidth={3} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-card__head">
          <div><span className="eyebrow">Why?</span><h3>Issue themes</h3></div>
          <span>{issueTotal} signals</span>
        </div>
        <div className="chart-frame chart-frame--donut">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={issueThemes}
                dataKey="count"
                nameKey="label"
                innerRadius={58}
                outerRadius={88}
                paddingAngle={3}
                onMouseEnter={(_, index) => setActiveThemeIndex(index)}
                onMouseLeave={() => setActiveThemeIndex(0)}
              >
                {issueThemes.map((theme, index) => (
                  <Cell
                    key={theme.label}
                    fill={[COLORS.red, COLORS.yellow, COLORS.purple, COLORS.cyan, COLORS.green][index]}
                    tabIndex={0}
                    onFocus={() => setActiveThemeIndex(index)}
                    onBlur={() => setActiveThemeIndex(0)}
                  />
                ))}
              </Pie>
              <Tooltip content={() => null} cursor={false} />
              <Legend iconType="circle" verticalAlign="middle" align="right" layout="vertical" wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="donut-center" aria-live="polite"><strong>{activeTheme?.count ?? 0}</strong><span>{activeTheme?.label ?? "top issue"}</span></div>
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-card__head">
          <div><span className="eyebrow">Where?</span><h3>Affected products</h3></div>
          <span>{data.affectedProducts.length} products</span>
        </div>
        <div className="rank-bars">
          {data.affectedProducts.map((product) => (
            <button key={product.id} type="button" onClick={() => onSelectProduct(product.id)}>
              <span className="rank-bars__label"><strong>{product.shortName}</strong><small>{product.current.complaints}/{product.current.reviews}</small></span>
              <span className="rank-bars__track"><i style={{ width: `${(product.current.complaints / maxProductComplaints) * 100}%` }} /></span>
              <strong>{((product.current.complaints / product.current.reviews) * 100).toFixed(1)}%</strong>
            </button>
          ))}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-card__head">
          <div><span className="eyebrow">Which channel?</span><h3>Signal sources</h3></div>
          <span>Cross-channel</span>
        </div>
        <div className="chart-frame chart-frame--bar">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.sourceCounts} layout="vertical" margin={{ top: 6, right: 26, bottom: 0, left: 18 }}>
              <CartesianGrid horizontal={false} stroke="rgba(128,135,142,.14)" />
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="label" width={112} axisLine={false} tickLine={false} tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <Tooltip cursor={{ fill: "rgba(255,255,255,.025)" }} contentStyle={{ background: "#141616", border: "1px solid #333", borderRadius: 8 }} />
              <Bar dataKey="count" name="Signals" fill={COLORS.cyan} radius={[0, 4, 4, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-card__head">
          <div><span className="eyebrow">Compared with peers</span><h3>Complaint benchmark</h3></div>
          <span>Same cohort</span>
        </div>
        <div className="chart-frame chart-frame--bar">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={[{ name: "Guardian", share: data.complaintShare ?? 0 }, ...data.competitors.map((item) => ({ name: item.retailer === "hasaki" ? "Hasaki" : "Watsons", share: item.share ?? 0 }))]} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid vertical={false} stroke="rgba(128,135,142,.14)" />
              <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <YAxis unit="%" axisLine={false} tickLine={false} tick={{ fill: COLORS.muted, fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#141616", border: "1px solid #333", borderRadius: 8 }} />
              <Bar dataKey="share" name="Complaint share" radius={[5, 5, 0, 0]} barSize={38}>
                {[COLORS.yellow, COLORS.cyan, COLORS.purple].map((color) => <Cell key={color} fill={color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="insight-card insight-card--wide heatmap-card">
        <div className="insight-card__head">
          <div><span className="eyebrow">Product × issue</span><h3>Concentration heatmap</h3></div>
          <span>Darker = more concentrated</span>
        </div>
        <div className="heatmap" role="table" aria-label="Product by issue concentration">
          <div className="heatmap__row heatmap__head" role="row">
            <span>Product</span>{data.themes.slice(0, 4).map((theme) => <span key={theme.label}>{theme.label}</span>)}
          </div>
          {data.affectedProducts.map((product) => (
            <div className="heatmap__row" role="row" key={product.id}>
              <strong>{product.shortName}</strong>
              {data.themes.slice(0, 4).map((theme) => {
                const value = product.themes.find((item) => item.label === theme.label)?.count ?? 0;
                const opacity = value ? 0.18 + (value / Math.max(1, theme.count)) * 0.72 : 0.035;
                return <span key={theme.label} style={{ backgroundColor: `rgba(239,90,90,${opacity})` }}>{value || "—"}</span>;
              })}
            </div>
          ))}
        </div>
      </section>

      <section className="constellation-card insight-card--wide">
        <div className="constellation-card__head">
          <div>
            <span className="eyebrow">How is it connected?</span>
            <h3>Signal constellation</h3>
            <p>Products linked through shared issue themes, customer evidence, hypotheses and actions.</p>
          </div>
          <div className="constellation-card__controls">
            <select aria-label="Filter graph nodes" value={nodeFilter} onChange={(event) => setNodeFilter(event.target.value as NodeKind | "all")}>
              <option value="all">All relationships</option>
              <option value="issue">Issues</option>
              <option value="evidence">Evidence</option>
              <option value="hypothesis">Hypotheses</option>
              <option value="action">Actions</option>
            </select>
            <div className="mode-toggle" aria-label="Graph view">
              <button className={graphMode === "2d" ? "is-active" : ""} type="button" onClick={() => setGraphMode("2d")}>2D</button>
              <button className={graphMode === "3d" ? "is-active" : ""} type="button" onClick={() => setGraphMode("3d")}>3D</button>
            </div>
          </div>
        </div>
        <div className="constellation-legend">
          {(Object.keys(NODE_COLORS) as NodeKind[]).map((kind) => <span key={kind}><i style={{ background: NODE_COLORS[kind] }} />{kind}</span>)}
          <em><GitBranch size={15} /> {filteredGraph.nodes.length} nodes · {filteredGraph.links.length} links</em>
        </div>
        <div className={`constellation-canvas constellation-canvas--${graphMode}`} ref={graphWrapRef}>
          {!canRenderCanvas ? (
            <div className="graph-loading">Interactive graph is available in the browser.</div>
          ) : (
            <Suspense fallback={<div className="graph-loading">Loading signal constellation…</div>}>
              {graphMode === "2d" ? (
                <ForceGraph2D
              graphData={filteredGraph}
              width={graphWidth}
              height={520}
              backgroundColor="rgba(0,0,0,0)"
              nodeLabel={(node) => `${node.name} · ${node.kind}`}
              nodeColor={(node) => node.color}
              nodeVal={(node) => node.value}
              linkColor={() => "rgba(137,145,151,.24)"}
              linkWidth={1}
              cooldownTicks={90}
              onNodeClick={(node) => setSelectedNode({ name: String(node.name), kind: node.kind as NodeKind })}
                />
              ) : (
                <ForceGraph3D
              graphData={filteredGraph}
              width={graphWidth}
              height={520}
              backgroundColor="rgba(7,9,10,1)"
              nodeLabel={(node) => `${node.name} · ${node.kind}`}
              nodeColor={(node) => node.color}
              nodeVal={(node) => node.value}
              linkColor={() => "rgba(153,162,170,.32)"}
              linkOpacity={0.5}
              onNodeClick={(node) => setSelectedNode({ name: String(node.name), kind: node.kind as NodeKind })}
                />
              )}
            </Suspense>
          )}
          <div className="graph-hint"><Cube size={17} /> {graphMode === "3d" ? "Drag to rotate · Scroll to zoom" : "Drag nodes · Scroll to zoom"}</div>
          {selectedNode && (
            <aside className="node-detail">
              <button type="button" aria-label="Close node details" onClick={() => setSelectedNode(null)}>×</button>
              <span className="eyebrow">{selectedNode.kind}</span>
              <strong>{selectedNode.name}</strong>
              <small>Connected context is highlighted in the current product cohort.</small>
            </aside>
          )}
        </div>
      </section>
    </div>
  );
}
