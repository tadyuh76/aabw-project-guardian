import { Badge, Box, Button, Flex, Grid, Heading, Stack, Text } from "@chakra-ui/react";
import { ArrowDown, ArrowRight, ArrowUp, ChatCircleDots, CheckCircle, Package, Pulse, Star, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import type { DashboardData, DashboardProduct, ProductRatingTrendPoint, ProductTheme } from "../api/types";
import { cleanDisplayText } from "../utils/displayText";
import { ProductFilter } from "./ProductFilter";

interface DashboardProps { data: DashboardData; }
type TimeScope = "current" | "baseline";

const chartColors = ["#f97316", "#2563eb", "#16a34a", "#7c3aed", "#e11d48"];
const ratingColor = "#f97316";
const platformColors: Record<string, string> = {
  "TikTok Shop": "#18181b",
  Shopee: "#f97316",
  Lazada: "#7c3aed",
  GrabMart: "#16a34a",
};
const panelProps = { bg: "surface", borderWidth: "1px", borderColor: "border", borderRadius: "panel", p: { base: "5", md: "6" } } as const;

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}

function percent(value: number | null, digits = 1): string {
  return value === null ? "-" : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: digits }).format(value);
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function aggregateThemes(products: DashboardProduct[], key: "negativeFeedback" | "problems"): ProductTheme[] {
  const values = new Map<string, { count: number; baselineCount: number }>();
  products.forEach((product) => product[key].forEach((item) => {
    const current = values.get(item.label) ?? { count: 0, baselineCount: 0 };
    current.count += item.count;
    current.baselineCount += item.baselineCount;
    values.set(item.label, current);
  }));
  return [...values.entries()].map(([label, value]) => ({
    label,
    subtopic: null,
    count: value.count,
    baselineCount: value.baselineCount,
    percentageChange: value.baselineCount ? 100 * (value.count - value.baselineCount) / value.baselineCount : null,
  })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Box {...panelProps} minW="0">
      <Flex align="center" justify="space-between" gap="4" mb="5">
        <Heading size="md" letterSpacing="0">{title}</Heading>
        {action}
      </Flex>
      {children}
    </Box>
  );
}

function ChangeBadge({ value }: { value: number | null }) {
  if (value === null) return <Badge colorPalette="gray" variant="subtle">New</Badge>;
  const improved = value < 0;
  return (
    <Badge colorPalette={improved ? "green" : value > 0 ? "red" : "gray"} variant="subtle">
      {value > 0 ? <ArrowUp size={12} /> : value < 0 ? <ArrowDown size={12} /> : null}
      {Math.abs(value).toFixed(0)}%
    </Badge>
  );
}

function RatingBars({ items }: { items: Array<{ label: string; count: number }> }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <Grid gridTemplateColumns="repeat(5, minmax(0, 1fr))" gap={{ base: "2", md: "3" }} h="190px" alignItems="end">
      {items.map((item) => (
        <Flex key={item.label} direction="column" align="center" justify="flex-end" h="full" gap="2">
          <Text fontWeight="750">{item.count.toLocaleString()}</Text>
          <Flex w="full" maxW="54px" h={`${Math.max(8, (item.count / max) * 112)}px`} bg={ratingColor} borderRadius="6px 6px 2px 2px" transition="height .25s ease" />
          <Flex align="center" gap="1" fontWeight="700"><Star size={16} weight="fill" color={ratingColor} />{item.label}</Flex>
        </Flex>
      ))}
    </Grid>
  );
}

function IssueBars({ items, scope, empty }: { items: ProductTheme[]; scope: TimeScope; empty: string }) {
  const displayed = items.map((item) => ({ ...item, displayCount: scope === "current" ? item.count : item.baselineCount }));
  const max = Math.max(1, ...displayed.map((item) => item.displayCount));
  if (!displayed.some((item) => item.displayCount > 0)) return <Text color="muted">{empty}</Text>;
  return (
    <Stack gap="4">
      {displayed.map((item, index) => (
        <Box key={item.label}>
          <Flex justify="space-between" align="center" gap="3" mb="2">
            <Text fontWeight="650" lineClamp="1">{humanize(item.label)}</Text>
            <Flex align="center" gap="2" flexShrink="0">
              <ChangeBadge value={item.percentageChange} />
              <Text fontWeight="750" minW="32px" textAlign="right">{item.displayCount.toLocaleString()}</Text>
            </Flex>
          </Flex>
          <Box h="10px" bg="subtle" borderRadius="full" overflow="hidden">
            <Box h="full" borderRadius="full" bg={chartColors[(index + 1) % chartColors.length]} width={`${Math.max(2, (item.displayCount / max) * 100)}%`} />
          </Box>
        </Box>
      ))}
    </Stack>
  );
}

function aggregateRatingTrend(products: DashboardProduct[]): ProductRatingTrendPoint[] {
  const groups = new Map<string, { total: number; count: number; point: ProductRatingTrendPoint }>();
  products.forEach((product) => product.ratingTrend.forEach((point) => {
    const key = `${point.platform}|${point.date}|${point.predicted}`;
    const current = groups.get(key) ?? { total: 0, count: 0, point };
    const weight = Math.max(1, point.count);
    current.total += point.averageRating * weight;
    current.count += weight;
    groups.set(key, current);
  }));
  return [...groups.values()].map(({ total, count, point }) => ({ ...point, averageRating: total / count, count }));
}

function RatingTrendChart({ points }: { points: ProductRatingTrendPoint[] }) {
  const platforms = Object.keys(platformColors).filter((platform) => points.some((point) => point.platform === platform));
  const dates = [...new Set(points.map((point) => point.date))].sort();
  if (!platforms.length || dates.length < 2) return <Text color="muted">A dated platform rating series is not available yet.</Text>;
  const width = 820;
  const height = 290;
  const left = 48;
  const right = 18;
  const top = 18;
  const bottom = 46;
  const x = (date: string) => left + (dates.indexOf(date) / Math.max(1, dates.length - 1)) * (width - left - right);
  const y = (rating: number) => top + ((5 - rating) / 4) * (height - top - bottom);
  const firstPrediction = dates.find((date) => points.some((point) => point.date === date && point.predicted));
  const predictionX = firstPrediction ? Math.max(left, x(firstPrediction) - ((width - left - right) / Math.max(1, dates.length - 1)) / 2) : width;
  const line = (items: ProductRatingTrendPoint[]) => items.map((point, index) => `${index ? "L" : "M"}${x(point.date).toFixed(1)},${y(point.averageRating).toFixed(1)}`).join(" ");
  return (
    <Stack gap="4">
      <Box overflowX="auto">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historical and predicted average ratings by marketplace" style={{ width: "100%", minWidth: "620px", display: "block" }}>
          <rect x={predictionX} y="0" width={width - predictionX} height={height - bottom + 12} fill="var(--chakra-colors-subtle)" opacity="0.72" />
          {[1, 2, 3, 4, 5].map((rating) => <g key={rating}><line x1={left} y1={y(rating)} x2={width - right} y2={y(rating)} stroke="var(--chakra-colors-border)" /><text x={left - 12} y={y(rating) + 5} textAnchor="end" fill="var(--chakra-colors-muted)" fontSize="13">{rating}.0</text></g>)}
          {firstPrediction && <text x={predictionX + 12} y="18" fill="var(--chakra-colors-muted)" fontSize="13" fontWeight="600">PREDICTED</text>}
          {platforms.map((platform) => {
            const platformPoints = points.filter((point) => point.platform === platform).sort((a, b) => a.date.localeCompare(b.date));
            const observed = platformPoints.filter((point) => !point.predicted);
            const predicted = platformPoints.filter((point) => point.predicted);
            const projected = observed.length && predicted.length ? [observed[observed.length - 1]!, ...predicted] : predicted;
            return <g key={platform}><path d={line(observed)} fill="none" stroke={platformColors[platform]} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />{projected.length > 1 && <path d={line(projected)} fill="none" stroke={platformColors[platform]} strokeWidth="3" strokeDasharray="8 7" strokeLinecap="round" />}{platformPoints.map((point) => <circle key={`${point.date}-${point.predicted}`} cx={x(point.date)} cy={y(point.averageRating)} r="4" fill={point.predicted ? "var(--chakra-colors-surface)" : platformColors[platform]} stroke={platformColors[platform]} strokeWidth="2.5" />)}</g>;
          })}
          {dates.map((date, index) => (index === 0 || index === dates.length - 1 || index % 2 === 0) && <text key={date} x={x(date)} y={height - 14} textAnchor="middle" fill="var(--chakra-colors-muted)" fontSize="13">{new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(new Date(`${date}T00:00:00`))}</text>)}
        </svg>
      </Box>
      <Flex gap="5" wrap="wrap">
        {platforms.map((platform) => <Flex key={platform} align="center" gap="2"><Box w="10px" h="10px" borderRadius="full" bg={platformColors[platform]} /><Text fontWeight="600">{platform}</Text></Flex>)}
      </Flex>
    </Stack>
  );
}

function hasUsefulInsight(data: DashboardData): boolean {
  const title = data.primaryInsight?.title.trim() ?? "";
  return Boolean(title && !/^ai auto summary$/i.test(title));
}

export function Dashboard({ data }: DashboardProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => data.products.map((product) => product.id));
  const [timeScope, setTimeScope] = useState<TimeScope>("current");
  useEffect(() => setSelectedIds(data.products.map((product) => product.id)), [data]);

  const selectedProducts = useMemo(() => data.products.filter((product) => selectedIds.includes(product.id)), [data.products, selectedIds]);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedEvidence = data.evidence.filter((item) => item.productId === null || selectedSet.has(item.productId));
  const totals = selectedProducts.reduce((result, product) => {
    const period = product[timeScope];
    return { feedback: result.feedback + period.feedback, complaints: result.complaints + period.complaints, positive: result.positive + period.positive, neutral: result.neutral + period.neutral };
  }, { feedback: 0, complaints: 0, positive: 0, neutral: 0 });
  const negative = Math.max(0, totals.feedback - totals.positive - totals.neutral);
  const ratingCounts = new Map<number, number>([5, 4, 3, 2, 1].map((rating) => [rating, 0]));
  selectedProducts.forEach((product) => (timeScope === "current" ? product.ratingDistribution : product.baselineRatingDistribution).forEach((item) => ratingCounts.set(item.rating, (ratingCounts.get(item.rating) ?? 0) + item.count)));
  const ratingDistribution = [5, 4, 3, 2, 1].map((rating) => ({ label: String(rating), count: ratingCounts.get(rating) ?? 0 }));
  const periodIssueSort = (a: ProductTheme, b: ProductTheme) => timeScope === "current"
    ? b.count - a.count || a.label.localeCompare(b.label)
    : b.baselineCount - a.baselineCount || a.label.localeCompare(b.label);
  const negativeFeedback = aggregateThemes(selectedProducts, "negativeFeedback").sort(periodIssueSort).slice(0, 5);
  const problems = aggregateThemes(selectedProducts, "problems").sort(periodIssueSort).slice(0, 5);
  const ratingTrend = aggregateRatingTrend(selectedProducts);
  const heroProduct = [...selectedProducts].sort((a, b) => (ratio(b.current.complaints, b.current.feedback) ?? 0) - (ratio(a.current.complaints, a.current.feedback) ?? 0))[0];
  const insight = hasUsefulInsight(data) ? data.primaryInsight : null;

  const metrics = [
    { icon: <ChatCircleDots size={34} />, label: "Reviews", value: totals.feedback.toLocaleString(), iconBg: "#eff6ff", darkIconBg: "#10233f", color: "#2563eb" },
    { icon: <CheckCircle size={34} weight="fill" />, label: "Positive", value: percent(ratio(totals.positive, totals.feedback), 0), iconBg: "#ecfdf3", darkIconBg: "#102b20", color: "#16a34a" },
    { icon: <Pulse size={34} weight="fill" />, label: "Neutral", value: percent(ratio(totals.neutral, totals.feedback), 0), iconBg: "#fff7e6", darkIconBg: "#38260d", color: "#d97706" },
    { icon: <WarningCircle size={34} weight="fill" />, label: "Negative", value: percent(ratio(negative, totals.feedback), 0), iconBg: "#fff1f2", darkIconBg: "#3a151c", color: "#e11d48" },
  ];

  return (
    <Stack gap="5">
      <Flex align={{ base: "stretch", md: "center" }} justify="space-between" direction={{ base: "column", md: "row" }} gap="4">
        <Flex role="group" aria-label="Analysis period" p="1" bg="subtle" borderRadius="control" gap="1" alignSelf="flex-start">
          <Button size="sm" variant={timeScope === "current" ? "solid" : "ghost"} colorPalette="orange" onClick={() => setTimeScope("current")}>Current 7 days</Button>
          <Button size="sm" variant={timeScope === "baseline" ? "solid" : "ghost"} colorPalette="orange" onClick={() => setTimeScope("baseline")}>Previous 28 days</Button>
        </Flex>
        <ProductFilter products={data.products} selectedIds={selectedIds} onChange={setSelectedIds} />
      </Flex>

      {selectedProducts.length === 0 ? (
        <Stack {...panelProps} align="flex-start" gap="4"><Package size={30} /><Heading size="lg">No products selected</Heading><Button colorPalette="orange" onClick={() => setSelectedIds(data.products.map((product) => product.id))}>Show products</Button></Stack>
      ) : <>
        {insight && <Grid as="section" aria-labelledby="pulse-title" {...panelProps} bg="#fff7ed" _dark={{ bg: "#30190c" }} borderColor="#fed7aa" gridTemplateColumns={{ base: "1fr", md: "auto 1fr auto" }} alignItems="center" gap="5">
          <Flex w="14" h="14" align="center" justify="center" borderRadius="full" bg="#ffedd5" color="#ea580c"><Star size={30} weight="fill" /></Flex>
          <Box><Heading id="pulse-title" size="lg" letterSpacing="0">{cleanDisplayText(insight.title)}</Heading>{insight.summary && <Text color="muted" mt="2">{cleanDisplayText(insight.summary)}</Text>}</Box>
          {heroProduct && <Button variant="outline" colorPalette="orange" onClick={() => setSelectedIds([heroProduct.id])}>Focus <ArrowRight size={16} /></Button>}
        </Grid>}

        <Grid as="section" aria-label="Sentiment metrics" gridTemplateColumns={{ base: "repeat(2, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap="4">
          {metrics.map((metric) => <Flex key={metric.label} minH={{ base: "146px", md: "128px" }} p={{ base: "5", md: "5" }} gap={{ base: "2", md: "4" }} direction={{ base: "column", md: "row" }} justify={{ base: "center", md: "flex-start" }} align="center" bg="surface" borderWidth="1px" borderTopWidth="3px" borderColor="border" borderTopColor={metric.color} borderRadius="panel">
            <Flex color={metric.color} bg={metric.iconBg} _dark={{ bg: metric.darkIconBg }} w={{ base: "12", md: "13" }} h={{ base: "12", md: "13" }} borderRadius="control" align="center" justify="center" flex="0 0 auto">{metric.icon}</Flex>
            <Box minW="0" textAlign={{ base: "center", md: "left" }}><Text color="muted" fontWeight="600" whiteSpace="nowrap">{metric.label}</Text><Text fontSize={{ base: "2xl", md: "3xl" }} lineHeight="1.1" fontWeight="780" letterSpacing="0" whiteSpace="nowrap">{metric.value}</Text></Box>
          </Flex>)}
        </Grid>

        <Grid gridTemplateColumns={{ base: "1fr", xl: "repeat(3, minmax(0, 1fr))" }} gap="4">
          <Section title="Rating distribution"><RatingBars items={ratingDistribution} /></Section>
          <Section title="Top 5 negative feedback"><IssueBars items={negativeFeedback} scope={timeScope} empty="No negative feedback in this period." /></Section>
          <Section title="Top 5 product problems"><IssueBars items={problems} scope={timeScope} empty="No product problems in this period." /></Section>
        </Grid>

        <Grid gridTemplateColumns={{ base: "1fr", xl: "minmax(0, 1.55fr) minmax(320px, .75fr)" }} gap="4">
          <Section title="Rating trend & forecast"><RatingTrendChart points={ratingTrend} /></Section>
          <Section title="Competitive sentiment">
            {!data.benchmark?.comparable ? <Text color="muted">{cleanDisplayText(data.benchmark?.reason ?? "Comparison not available.")}</Text> : <Stack gap="5">
              {data.benchmark.brands.map((brand, index) => {
                const negativeMentions = Math.max(0, (brand.feedback ?? 0) - (brand.positive ?? 0) - (brand.neutral ?? 0));
                const score = brand.feedback ? 50 + 50 * (((brand.positive ?? 0) - negativeMentions) / brand.feedback) : null;
                return <Box key={brand.brand}><Flex justify="space-between" mb="2"><Text fontWeight="650">{humanize(brand.brand)}</Text><Text fontWeight="780">{score === null ? "-" : score.toFixed(1)}</Text></Flex><Box h="12px" bg="subtle" borderRadius="full" overflow="hidden"><Box h="full" bg={chartColors[index % chartColors.length]} borderRadius="full" width={`${score ?? 0}%`} /></Box></Box>;
              })}
              <Text color="muted">Net Sentiment Score · 0-100</Text>
            </Stack>}
          </Section>
        </Grid>

        {selectedEvidence.length > 0 && <Section title="Recent review signals" action={<Badge variant="subtle" colorPalette="orange">{selectedEvidence.length}</Badge>}><Stack gap="0" divideY="1px" divideColor="border">{selectedEvidence.slice(0, 4).map((item) => <Grid key={item.id} py="4" gridTemplateColumns={{ base: "1fr", md: "130px minmax(0, 1fr) auto" }} gap="4" alignItems="start"><Text fontWeight="650">{humanize(cleanDisplayText(item.sourcePlatform))}</Text><Text>“{cleanDisplayText(item.text)}”</Text><Badge colorPalette={item.sentiment === "positive" ? "green" : item.sentiment === "negative" ? "red" : "gray"} variant="subtle">{humanize(item.sentiment ?? "neutral")}</Badge></Grid>)}</Stack></Section>}
      </>}
    </Stack>
  );
}
