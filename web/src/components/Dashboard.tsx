import { Badge, Box, Button, Flex, Grid, Heading, Input, Stack, Text } from "@chakra-ui/react";
import { ArrowSquareOut, CalendarBlank, ChatCircleDots, CheckCircle, Package, Pulse, Star, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import type { DashboardData, DashboardProduct, ProductRatingTrendPoint, ProductTheme } from "../api/types";
import { cleanDisplayText } from "../utils/displayText";
import { GUARDIAN_PRODUCT_GROUPS, ProductGroupSelect, productMatchesGroup } from "./ProductGroupSelect";

interface DashboardProps { data: DashboardData; }
type DatePreset = "7d" | "30d" | "1y" | "all" | "custom";
type DateMode = "current" | "combined";

const chartColors = ["#ec7e24", "#2563eb", "#16a34a", "#7c3aed", "#e11d48"];
const ratingColor = "#ec7e24";
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

function DateRangeFilter({ value, onChange, customRange, onCustomRangeChange }: { value: DatePreset; onChange: (value: DatePreset) => void; customRange: { from: string; to: string }; onCustomRangeChange: (value: { from: string; to: string }) => void }) {
  const presets: Array<{ value: DatePreset; label: string }> = [
    { value: "7d", label: "7D" },
    { value: "30d", label: "30D" },
    { value: "1y", label: "1Y" },
    { value: "all", label: "All" },
    { value: "custom", label: "Custom" },
  ];
  const customDateField = (label: string, field: "from" | "to") => (
    <Flex align="center" gap="2" px="3" h="40px" borderWidth="1px" borderColor="border" borderRadius="control" bg="surface">
      <CalendarBlank size={16} />
      <Input
        type="text"
        inputMode="numeric"
        aria-label={label}
        placeholder="dd/mm/yyyy"
        value={customRange[field]}
        onChange={(event) => onCustomRangeChange({ ...customRange, [field]: event.target.value })}
        border="0"
        px="0"
        h="36px"
        width="126px"
        _focusVisible={{ outline: "none", boxShadow: "none" }}
      />
    </Flex>
  );

  return (
    <Flex align="center" gap="2" wrap="wrap">
      <Flex role="group" aria-label="Date range" p="1" bg="surface" borderWidth="1px" borderColor="border" borderRadius="control" gap="1" alignSelf="flex-start">
        {presets.map((preset) => (
          <Button key={preset.value} size="sm" minW="12" variant={value === preset.value ? "solid" : "ghost"} colorPalette="orange" onClick={() => onChange(preset.value)}>
            {preset.label}
          </Button>
        ))}
      </Flex>
      {value === "custom" && (
        <Flex align="center" gap="2" wrap="wrap">
          {customDateField("Custom start date", "from")}
          {customDateField("Custom end date", "to")}
        </Flex>
      )}
    </Flex>
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

function ProblemCategoryChart({ items, mode, empty }: { items: ProductTheme[]; mode: DateMode; empty: string }) {
  const displayed = items.map((item) => ({
    ...item,
    displayCount: mode === "current" ? item.count : item.count + item.baselineCount,
  }));
  const max = Math.max(1, ...displayed.map((item) => item.displayCount));
  if (!displayed.some((item) => item.displayCount > 0)) return <Text color="muted">{empty}</Text>;
  const width = 420;
  const rowHeight = 36;
  const top = 10;
  const right = 42;
  const labelWidth = 138;
  const barWidth = width - labelWidth - right;
  const height = top * 2 + displayed.length * rowHeight;
  return (
    <Box overflowX="auto">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Top product problem categories" style={{ width: "100%", minWidth: "300px", display: "block" }}>
        {[0.5, 1].map((tick) => (
          <line
            key={tick}
            x1={labelWidth + tick * barWidth}
            y1="0"
            x2={labelWidth + tick * barWidth}
            y2={height}
            stroke="var(--chakra-colors-border)"
            strokeDasharray="4 6"
          />
        ))}
        {displayed.map((item, index) => {
          const y = top + index * rowHeight;
          const bar = Math.max(4, (item.displayCount / max) * barWidth);
          const label = humanize(item.label);
          return (
            <g key={item.label}>
              <text x="0" y={y + 21} fill="var(--chakra-colors-ink)" fontSize="13" fontWeight="650">
                {label.length > 22 ? `${label.slice(0, 21)}…` : label}
              </text>
              <rect x={labelWidth} y={y + 8} width={bar} height="16" rx="4" fill={chartColors[(index + 1) % chartColors.length]} />
              <text x={labelWidth + bar + 8} y={y + 21} fill="var(--chakra-colors-ink)" fontSize="13" fontWeight="750">
                {item.displayCount.toLocaleString()}
              </text>
            </g>
          );
        })}
      </svg>
    </Box>
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
  const width = 560;
  const height = 250;
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
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historical and predicted average ratings by marketplace" style={{ width: "100%", minWidth: "320px", display: "block" }}>
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

function SocialExperienceScore({ benchmark }: { benchmark: DashboardData["benchmark"] }) {
  if (!benchmark?.comparable) return <Text color="muted">{cleanDisplayText(benchmark?.reason ?? "Comparison not available.")}</Text>;
  return (
    <Stack gap="5">
      {benchmark.brands.map((brand, index) => {
        const totalMentions = brand.feedback ?? 0;
        const positiveMentions = brand.positive ?? 0;
        const negativeMentions = Math.max(0, totalMentions - positiveMentions - (brand.neutral ?? 0));
        const score = totalMentions ? 50 + 50 * ((positiveMentions - negativeMentions) / totalMentions) : null;
        return (
          <Box key={brand.brand}>
            <Flex justify="space-between" mb="2" gap="3">
              <Text fontWeight="650">{humanize(brand.brand)}</Text>
              <Text fontWeight="780">{score === null ? "-" : score.toFixed(1)}</Text>
            </Flex>
            <Box h="12px" bg="subtle" borderRadius="full" overflow="hidden">
              <Box h="full" bg={chartColors[index % chartColors.length]} borderRadius="full" width={`${Math.max(0, Math.min(100, score ?? 0))}%`} />
            </Box>
          </Box>
        );
      })}
      <Text color="muted" fontSize="sm">
        So sánh hiệu suất cạnh tranh bằng Net Sentiment Score = 50 + 50 * ((Positive Mentions - Negative Mentions) / Total Mentions) để đo lường sự hài lòng của khách hàng và phản ánh thái độ của họ.
      </Text>
    </Stack>
  );
}

function hasUsefulInsight(data: DashboardData): boolean {
  const title = data.primaryInsight?.title.trim() ?? "";
  return Boolean(title && !/^ai auto summary$/i.test(title));
}

function weeklySummaryMessage({ insight, feedback, positive, neutral, issue }: { insight: DashboardData["primaryInsight"]; feedback: number; positive: number; neutral: number; issue?: ProductTheme }): string {
  if (insight) return cleanDisplayText(insight.title);
  if (feedback <= 0) return "No resolved customer feedback this week.";
  const negative = Math.max(0, feedback - positive - neutral);
  if (positive >= negative && issue && issue.count > 0) return `Customers are mostly happy, but ${humanize(issue.label).toLocaleLowerCase()} needs action now.`;
  if (positive >= negative) return "Customers are mostly happy this week.";
  if (issue && issue.count > 0) return `${humanize(issue.label)} needs action this week.`;
  return "Customer sentiment needs attention this week.";
}

function WeeklySummaryCard({ message }: { message: string }) {
  return (
    <Flex
      as="section"
      aria-label="Last week summary"
      position="relative"
      overflow="hidden"
      align="center"
      gap={{ base: "4", md: "6" }}
      minH={{ base: "118px", md: "128px" }}
      width="full"
      px={{ base: "5", md: "7" }}
      py={{ base: "5", md: "6" }}
      bg="surface"
      borderWidth="1px"
      borderColor="brand.200"
      borderRadius="panel"
      boxShadow="0 10px 30px rgba(236, 126, 36, 0.10)"
    >
      <Box position="absolute" inset="0" bg="linear-gradient(100deg, rgba(255,248,241,0.95) 0%, rgba(255,255,255,0.95) 58%, rgba(255,234,216,0.42) 100%)" pointerEvents="none" />
      <Flex position="relative" w={{ base: "14", md: "16" }} h={{ base: "14", md: "16" }} flex="0 0 auto" align="center" justify="center" borderRadius="full" bg="brand.100" color="brand.500">
        <Flex w={{ base: "10", md: "12" }} h={{ base: "10", md: "12" }} align="center" justify="center" borderRadius="full" bg="brand.500" color="white">
          <Star size={28} weight="fill" />
        </Flex>
      </Flex>
      <Box position="relative" minW="0" maxW="980px">
        <Badge mb="2" colorPalette="orange" variant="subtle">AI summary</Badge>
        <Heading size={{ base: "md", md: "xl" }} lineHeight="1.28" letterSpacing="0">
          {message}
        </Heading>
      </Box>
      <Flex
        position="relative"
        display={{ base: "none", md: "flex" }}
        ml="auto"
        flex="0 0 auto"
        align="center"
        justify="center"
        w="178px"
        h="86px"
        color="brand.500"
        aria-hidden="true"
      >
        <Stack position="absolute" left="0" gap="2" align="flex-start">
          <Box h="3px" w="62px" bg="brand.300" borderRadius="full" />
          <Box h="3px" w="42px" bg="brand.200" borderRadius="full" />
          <Box h="3px" w="78px" bg="brand.100" borderRadius="full" />
        </Stack>
        <Flex position="relative" ml="10" w="58px" h="58px" align="center" justify="center" bg="brand.500" color="white" borderRadius="14px" boxShadow="0 12px 26px rgba(236, 126, 36, 0.22)">
          <Package size={34} weight="bold" />
        </Flex>
        <Box position="absolute" right="20px" bottom="9px" w="34px" h="4px" bg="brand.200" borderRadius="full" opacity="0.9" />
      </Flex>
    </Flex>
  );
}

export function Dashboard({ data }: DashboardProps) {
  const [datePreset, setDatePreset] = useState<DatePreset>("7d");
  const [customRange, setCustomRange] = useState({ from: "", to: "" });
  const [selectedGroupId, setSelectedGroupId] = useState("all");
  const selectedGroup = GUARDIAN_PRODUCT_GROUPS.find((group) => group.id === selectedGroupId) ?? GUARDIAN_PRODUCT_GROUPS[0]!;
  const dateMode: DateMode = datePreset === "7d" ? "current" : "combined";

  const selectedProducts = useMemo(() => data.products.filter((product) => productMatchesGroup(product, selectedGroup)), [data.products, selectedGroup]);
  const selectedSet = useMemo(() => new Set(selectedProducts.map((product) => product.id)), [selectedProducts]);
  const selectedEvidence = data.evidence.filter((item) => item.productId === null || selectedSet.has(item.productId));
  const totals = selectedProducts.reduce((result, product) => {
    const period = dateMode === "current"
      ? product.current
      : {
        feedback: product.current.feedback + product.baseline.feedback,
        complaints: product.current.complaints + product.baseline.complaints,
        positive: product.current.positive + product.baseline.positive,
        neutral: product.current.neutral + product.baseline.neutral,
      };
    return { feedback: result.feedback + period.feedback, complaints: result.complaints + period.complaints, positive: result.positive + period.positive, neutral: result.neutral + period.neutral };
  }, { feedback: 0, complaints: 0, positive: 0, neutral: 0 });
  const negative = Math.max(0, totals.feedback - totals.positive - totals.neutral);
  const ratingCounts = new Map<number, number>([5, 4, 3, 2, 1].map((rating) => [rating, 0]));
  selectedProducts.forEach((product) => {
    const distributions = dateMode === "current" ? [product.ratingDistribution] : [product.ratingDistribution, product.baselineRatingDistribution];
    distributions.flat().forEach((item) => ratingCounts.set(item.rating, (ratingCounts.get(item.rating) ?? 0) + item.count));
  });
  const ratingDistribution = [5, 4, 3, 2, 1].map((rating) => ({ label: String(rating), count: ratingCounts.get(rating) ?? 0 }));
  const displayedIssueCount = (item: ProductTheme) => dateMode === "current" ? item.count : item.count + item.baselineCount;
  const periodIssueSort = (a: ProductTheme, b: ProductTheme) => displayedIssueCount(b) - displayedIssueCount(a) || a.label.localeCompare(b.label);
  const problems = aggregateThemes(selectedProducts, "problems").sort(periodIssueSort).slice(0, 5);
  const ratingTrend = aggregateRatingTrend(selectedProducts);
  const insight = hasUsefulInsight(data) ? data.primaryInsight : null;
  const weeklyMessage = weeklySummaryMessage({ insight, feedback: totals.feedback, positive: totals.positive, neutral: totals.neutral, issue: problems[0] });

  const metrics = [
    { icon: <ChatCircleDots size={34} />, label: "Reviews", value: totals.feedback.toLocaleString(), iconBg: "#eff6ff", darkIconBg: "#10233f", color: "#2563eb" },
    { icon: <CheckCircle size={34} weight="fill" />, label: "Positive", value: percent(ratio(totals.positive, totals.feedback), 0), iconBg: "#ecfdf3", darkIconBg: "#102b20", color: "#16a34a" },
    { icon: <Pulse size={34} weight="fill" />, label: "Neutral", value: percent(ratio(totals.neutral, totals.feedback), 0), iconBg: "#fff7e6", darkIconBg: "#38260d", color: "#d97706" },
    { icon: <WarningCircle size={34} weight="fill" />, label: "Negative", value: percent(ratio(negative, totals.feedback), 0), iconBg: "#fff1f2", darkIconBg: "#3a151c", color: "#e11d48" },
  ];

  return (
    <Stack gap="5">
      <Flex
        as="header"
        align={{ base: "stretch", lg: "center" }}
        justify="space-between"
        direction={{ base: "column", lg: "row" }}
        gap="4"
      >
        <DateRangeFilter value={datePreset} onChange={setDatePreset} customRange={customRange} onCustomRangeChange={setCustomRange} />
        <ProductGroupSelect products={data.products} selectedGroupId={selectedGroupId} onChange={setSelectedGroupId} />
      </Flex>

      {selectedProducts.length === 0 ? (
        <Stack {...panelProps} align="flex-start" gap="4"><Package size={30} /><Heading size="lg">No products found in this group</Heading><Button colorPalette="orange" onClick={() => setSelectedGroupId("all")}>Show all groups</Button></Stack>
      ) : <>
        <WeeklySummaryCard message={weeklyMessage} />

        <Grid as="section" aria-label="Sentiment metrics" gridTemplateColumns={{ base: "repeat(2, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap="4">
          {metrics.map((metric) => <Flex key={metric.label} minH={{ base: "146px", md: "128px" }} p={{ base: "5", md: "5" }} gap={{ base: "2", md: "4" }} direction={{ base: "column", md: "row" }} justify={{ base: "center", md: "flex-start" }} align="center" bg="surface" borderWidth="1px" borderTopWidth="3px" borderColor="border" borderTopColor={metric.color} borderRadius="panel">
            <Flex color={metric.color} bg={metric.iconBg} _dark={{ bg: metric.darkIconBg }} w={{ base: "12", md: "13" }} h={{ base: "12", md: "13" }} borderRadius="control" align="center" justify="center" flex="0 0 auto">{metric.icon}</Flex>
            <Box minW="0" textAlign={{ base: "center", md: "left" }}><Text color="muted" fontWeight="600" whiteSpace="nowrap">{metric.label}</Text><Text fontSize={{ base: "2xl", md: "3xl" }} lineHeight="1.1" fontWeight="780" letterSpacing="0" whiteSpace="nowrap">{metric.value}</Text></Box>
          </Flex>)}
        </Grid>

        <Grid gridTemplateColumns={{ base: "1fr", md: "repeat(2, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap="4">
          <Section title="Rating distribution"><RatingBars items={ratingDistribution} /></Section>
          <Section title="Top 5 product problems"><ProblemCategoryChart items={problems} mode={dateMode} empty="No product problems in this period." /></Section>
          <Section title="Rating trend & forecast"><RatingTrendChart points={ratingTrend} /></Section>
          <Section title="Social experience score"><SocialExperienceScore benchmark={data.benchmark} /></Section>
        </Grid>

        {selectedEvidence.length > 0 && <Section title="Recent review signals" action={<Badge variant="subtle" colorPalette="orange">{selectedEvidence.length}</Badge>}><Stack gap="0" divideY="1px" divideColor="border">{selectedEvidence.slice(0, 4).map((item) => <Grid key={item.id} py="4" gridTemplateColumns={{ base: "1fr", md: "130px minmax(0, 1fr) auto" }} gap="4" alignItems="start"><Text fontWeight="650">{humanize(cleanDisplayText(item.sourcePlatform))}</Text><Text>“{cleanDisplayText(item.text)}”</Text><Flex gap="2" align="center" justify={{ base: "flex-start", md: "flex-end" }}><Badge colorPalette={item.sentiment === "positive" ? "green" : item.sentiment === "negative" ? "red" : "gray"} variant="subtle">{humanize(item.sentiment ?? "neutral")}</Badge>{item.sourceUrl && <Button asChild size="xs" variant="ghost" aria-label="Open source"><a href={item.sourceUrl} target="_blank" rel="noreferrer"><ArrowSquareOut weight="bold" /></a></Button>}</Flex></Grid>)}</Stack></Section>}
      </>}
    </Stack>
  );
}
