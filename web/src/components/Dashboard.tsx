import { Badge, Box, Button, Flex, Grid, Heading, Input, Stack, Text } from "@chakra-ui/react";
import { CalendarBlank, CaretLeft, CaretRight, ChatCircleDots, CheckCircle, DownloadSimple, Package, Pulse, Star, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useState } from "react";
import type { DashboardData, DashboardProduct, ProductRatingTrendPoint, ProductTheme } from "../api/types";
import { openDashboardPdfReport } from "../utils/dashboardPdf";
import { cleanDisplayText } from "../utils/displayText";

interface DashboardProps { data: DashboardData; }
type DatePreset = "7d" | "30d" | "1y" | "all" | "custom";
type DateMode = "current" | "combined" | "all";

const chartColors = ["#ec7e24", "#2563eb", "#16a34a", "#7c3aed", "#e11d48"];
const ratingColor = "#ec7e24";
const chartViewBoxWidth = 760;
const chartTextSize = 13;
const chartLabelSize = 14;
const chartValueSize = 13;
const platformColors: Record<string, string> = {
  "TikTok Shop": "#18181b",
  Shopee: "#f97316",
  Lazada: "#7c3aed",
  GrabMart: "#16a34a",
};
const panelProps = { bg: "surface", borderWidth: "1px", borderColor: "border", borderRadius: "panel", p: { base: "4", md: "5" } } as const;
const svgChartStyle = { width: "100%", minWidth: "340px", display: "block" } as const;

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}

function percent(value: number | null, digits = 1): string {
  return value === null ? "-" : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: digits }).format(value);
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function aggregateThemes(products: DashboardProduct[], key: "problems" | "allProblems"): ProductTheme[] {
  const values = new Map<string, { count: number; baselineCount: number }>();
  products.forEach((product) => (product[key] ?? []).forEach((item) => {
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
      <Flex align="center" justify="space-between" gap="4" mb="4">
        <Heading size="sm" letterSpacing="0">{title}</Heading>
        {action}
      </Flex>
      {children}
    </Box>
  );
}

function parseDisplayDate(value: string): Date | null {
  const trimmed = value.trim();
  const displayMatch = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(trimmed);
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  const day = displayMatch ? Number(displayMatch[1]) : isoMatch ? Number(isoMatch[3]) : null;
  const month = displayMatch ? Number(displayMatch[2]) : isoMatch ? Number(isoMatch[2]) : null;
  const year = displayMatch ? Number(displayMatch[3]) : isoMatch ? Number(isoMatch[1]) : null;
  if (day === null || month === null || year === null) return null;
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day ? date : null;
}

function formatDisplayDate(date: Date): string {
  return [
    String(date.getDate()).padStart(2, "0"),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getFullYear()),
  ].join("/");
}

function normalizeDateInput(value: string): string {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

function monthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function CalendarDateField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const selectedDate = parseDisplayDate(value);
  const [open, setOpen] = useState(false);
  const [viewMonth, setViewMonth] = useState(() => monthStart(selectedDate ?? new Date()));
  const monthLabel = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(viewMonth);
  const firstDay = new Date(viewMonth.getFullYear(), viewMonth.getMonth(), 1);
  const leadingBlanks = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 0).getDate();
  const cells = Array.from({ length: leadingBlanks + daysInMonth }, (_, index) => (
    index < leadingBlanks ? null : new Date(viewMonth.getFullYear(), viewMonth.getMonth(), index - leadingBlanks + 1)
  ));
  const openCalendar = () => {
    setViewMonth(monthStart(selectedDate ?? new Date()));
    setOpen(true);
  };

  return (
    <Box position="relative">
      <Flex align="center" gap="2" px="3" h="40px" borderWidth="1px" borderColor="border" borderRadius="control" bg="surface">
        <CalendarBlank size={16} />
        <Input
          type="text"
          inputMode="numeric"
          aria-label={label}
          placeholder="dd/mm/yyyy"
          value={value}
          onFocus={openCalendar}
          onClick={openCalendar}
          onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}
          onChange={(event) => {
            const next = normalizeDateInput(event.target.value);
            onChange(next);
            const parsed = parseDisplayDate(next);
            if (parsed) setViewMonth(monthStart(parsed));
          }}
          border="0"
          px="0"
          h="36px"
          width="126px"
          _focusVisible={{ outline: "none", boxShadow: "none" }}
        />
      </Flex>
      {open && (
        <Box position="absolute" zIndex="dropdown" top="calc(100% + 8px)" left="0" width="286px" p="3" bg="surface" borderWidth="1px" borderColor="border" borderRadius="panel" boxShadow="xl">
          <Flex align="center" justify="space-between" mb="3">
            <Button size="xs" variant="ghost" aria-label="Previous month" onClick={() => setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1))}><CaretLeft size={15} /></Button>
            <Text fontWeight="750">{monthLabel}</Text>
            <Button size="xs" variant="ghost" aria-label="Next month" onClick={() => setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1))}><CaretRight size={15} /></Button>
          </Flex>
          <Grid gridTemplateColumns="repeat(7, 1fr)" gap="1">
            {["M", "T", "W", "T", "F", "S", "S"].map((day, index) => <Text key={`${day}-${index}`} color="muted" fontSize="xs" fontWeight="700" textAlign="center">{day}</Text>)}
            {cells.map((date, index) => {
              const selected = Boolean(date && selectedDate && date.toDateString() === selectedDate.toDateString());
              return date ? (
                <Button key={date.toISOString()} size="xs" minW="0" variant={selected ? "solid" : "ghost"} colorPalette="orange" onClick={() => { onChange(formatDisplayDate(date)); setOpen(false); }}>
                  {date.getDate()}
                </Button>
              ) : <Box key={`blank-${index}`} h="8" />;
            })}
          </Grid>
        </Box>
      )}
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
  const customDateField = (label: string, field: "from" | "to") => <CalendarDateField label={label} value={customRange[field]} onChange={(next) => onCustomRangeChange({ ...customRange, [field]: next })} />;

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
          <Text fontSize="xs" fontWeight="750">{item.count.toLocaleString()}</Text>
          <Flex w="full" maxW="44px" h={`${Math.max(8, (item.count / max) * 104)}px`} bg={ratingColor} borderRadius="6px 6px 2px 2px" transition="height .25s ease" />
          <Flex align="center" gap="1" fontSize="xs" fontWeight="700"><Star size={13} weight="fill" color={ratingColor} />{item.label}</Flex>
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
  const width = chartViewBoxWidth;
  const rowHeight = 42;
  const top = 12;
  const right = 58;
  const labelWidth = 252;
  const barWidth = width - labelWidth - right;
  const height = top * 2 + displayed.length * rowHeight;
  return (
    <Box overflowX="auto">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Top product problem categories" style={svgChartStyle}>
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
              <text x="0" y={y + 25} fill="var(--chakra-colors-ink)" fontSize={chartLabelSize} fontWeight="650">
                {label.length > 30 ? `${label.slice(0, 29)}...` : label}
              </text>
              <rect x={labelWidth} y={y + 10} width={bar} height="18" rx="4" fill={chartColors[(index + 1) % chartColors.length]} />
              <text x={labelWidth + bar + 10} y={y + 25} fill="var(--chakra-colors-ink)" fontSize={chartValueSize} fontWeight="750">
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

function dateOnly(value: string | null): Date | null {
  if (!value) return null;
  const parsed = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function trendDateRange(data: DashboardData, preset: DatePreset, customRange: { from: string; to: string }): { start: Date | null; end: Date | null } {
  if (preset === "all") return { start: null, end: null };
  if (preset === "custom") {
    const start = parseDisplayDate(customRange.from);
    const end = parseDisplayDate(customRange.to);
    return { start, end: end ? addDays(end, 1) : null };
  }
  const currentEnd = dateOnly(data.windows.currentEnd) ?? new Date();
  if (preset === "7d") return { start: dateOnly(data.windows.currentStart) ?? addDays(currentEnd, -7), end: currentEnd };
  return { start: addDays(currentEnd, preset === "30d" ? -30 : -365), end: currentEnd };
}

function filterRatingTrend(points: ProductRatingTrendPoint[], range: { start: Date | null; end: Date | null }): ProductRatingTrendPoint[] {
  if (!range.start && !range.end) return points;
  const observed = points.filter((point) => {
    if (point.predicted) return false;
    const pointDate = dateOnly(point.date);
    if (!pointDate) return false;
    if (range.start && pointDate < range.start) return false;
    return !(range.end && pointDate >= range.end);
  });
  if (!observed.length) return [];
  const observedDates = observed.flatMap((point) => {
    const pointDate = dateOnly(point.date);
    return pointDate ? [pointDate.getTime()] : [];
  });
  const lastObservedTime = Math.max(...observedDates);
  const forecastEnd = addDays(range.end ?? new Date(lastObservedTime), 8);
  const predicted = points.filter((point) => {
    if (!point.predicted) return false;
    const pointDate = dateOnly(point.date);
    return Boolean(pointDate && pointDate.getTime() > lastObservedTime && pointDate < forecastEnd);
  });
  return [...observed, ...predicted];
}

function RatingTrendChart({ points }: { points: ProductRatingTrendPoint[] }) {
  const platforms = Object.keys(platformColors).filter((platform) => points.some((point) => point.platform === platform));
  const dates = [...new Set(points.map((point) => point.date))].sort();
  if (!platforms.length || dates.length < 2) return <Text color="muted">A dated platform rating series is not available yet.</Text>;
  const width = chartViewBoxWidth;
  const height = 250;
  const left = 56;
  const right = 22;
  const top = 18;
  const bottom = 46;
  const minRating = 3;
  const maxRating = 5;
  const ratingTicks = [3, 3.5, 4, 4.5, 5];
  const x = (date: string) => left + (dates.indexOf(date) / Math.max(1, dates.length - 1)) * (width - left - right);
  const y = (rating: number) => {
    const clamped = Math.max(minRating, Math.min(maxRating, rating));
    return top + ((maxRating - clamped) / (maxRating - minRating)) * (height - top - bottom);
  };
  const firstPrediction = dates.find((date) => points.some((point) => point.date === date && point.predicted));
  const predictionX = firstPrediction ? Math.max(left, x(firstPrediction) - ((width - left - right) / Math.max(1, dates.length - 1)) / 2) : width;
  const line = (items: ProductRatingTrendPoint[]) => items.map((point, index) => `${index ? "L" : "M"}${x(point.date).toFixed(1)},${y(point.averageRating).toFixed(1)}`).join(" ");
  return (
    <Stack gap="4">
      <Box overflowX="auto">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historical and predicted average ratings by marketplace" style={svgChartStyle}>
          <rect x={predictionX} y="0" width={width - predictionX} height={height - bottom + 12} fill="var(--chakra-colors-subtle)" opacity="0.72" />
          {ratingTicks.map((rating) => <g key={rating}><line x1={left} y1={y(rating)} x2={width - right} y2={y(rating)} stroke="var(--chakra-colors-border)" /><text x={left - 12} y={y(rating) + 4} textAnchor="end" fill="var(--chakra-colors-muted)" fontSize={chartTextSize}>{rating.toFixed(1)}</text></g>)}
          {firstPrediction && <text x={predictionX + 12} y="18" fill="var(--chakra-colors-muted)" fontSize={chartTextSize} fontWeight="600">PREDICTED</text>}
          {platforms.map((platform) => {
            const platformPoints = points.filter((point) => point.platform === platform).sort((a, b) => a.date.localeCompare(b.date));
            const observed = platformPoints.filter((point) => !point.predicted);
            const predicted = platformPoints.filter((point) => point.predicted);
            const projected = observed.length && predicted.length ? [observed[observed.length - 1]!, ...predicted] : predicted;
            return <g key={platform}><path d={line(observed)} fill="none" stroke={platformColors[platform]} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />{projected.length > 1 && <path d={line(projected)} fill="none" stroke={platformColors[platform]} strokeWidth="2.5" strokeDasharray="7 6" strokeLinecap="round" />}{platformPoints.map((point) => <circle key={`${point.date}-${point.predicted}`} cx={x(point.date)} cy={y(point.averageRating)} r="3.5" fill={point.predicted ? "var(--chakra-colors-surface)" : platformColors[platform]} stroke={platformColors[platform]} strokeWidth="2" />)}</g>;
          })}
          {dates.map((date, index) => (index === 0 || index === dates.length - 1 || index % 2 === 0) && <text key={date} x={x(date)} y={height - 14} textAnchor="middle" fill="var(--chakra-colors-muted)" fontSize={chartTextSize}>{new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(new Date(`${date}T00:00:00`))}</text>)}
        </svg>
      </Box>
      <Flex gap="4" wrap="wrap">
        {platforms.map((platform) => <Flex key={platform} align="center" gap="2"><Box w="8px" h="8px" borderRadius="full" bg={platformColors[platform]} /><Text fontSize="xs" fontWeight="600">{platform}</Text></Flex>)}
      </Flex>
    </Stack>
  );
}

function SocialExperienceScore({ benchmark }: { benchmark: DashboardData["benchmark"] }) {
  if (!benchmark?.comparable) return <Text color="muted">{cleanDisplayText(benchmark?.reason ?? "Comparison not available.")}</Text>;
  return (
    <Stack gap="5" pt="1">
      {benchmark.brands.map((brand, index) => {
        const totalMentions = brand.feedback ?? 0;
        const positiveMentions = brand.positive ?? 0;
        const negativeMentions = Math.max(0, totalMentions - positiveMentions - (brand.neutral ?? 0));
        const score = totalMentions ? 50 + 50 * ((positiveMentions - negativeMentions) / totalMentions) : null;
        return (
          <Box key={brand.brand}>
            <Flex justify="space-between" mb="2" gap="3">
              <Text fontSize="sm" fontWeight="650">{humanize(brand.brand)}</Text>
              <Text fontSize="sm" fontWeight="780">{score === null ? "-" : score.toFixed(1)}</Text>
            </Flex>
            <Box h="10px" bg="subtle" borderRadius="full" overflow="hidden">
              <Box h="full" bg={chartColors[index % chartColors.length]} borderRadius="full" width={`${Math.max(0, Math.min(100, score ?? 0))}%`} />
            </Box>
          </Box>
        );
      })}
    </Stack>
  );
}

function GuardianWordCloud({ terms }: { terms: DashboardData["wordCloud"] }) {
  const visibleTerms = terms.filter((term) => term.count > 0).slice(0, 60);
  if (!visibleTerms.length) return (
    <Section title="Guardian review keyword cloud">
      <Text color="muted">No Guardian review keywords are available yet.</Text>
    </Section>
  );
  const max = Math.max(...visibleTerms.map((term) => term.count));
  const min = Math.min(...visibleTerms.map((term) => term.count));
  const scale = (count: number) => {
    if (max === min) return 1;
    return (count - min) / (max - min);
  };
  return (
    <Section title="Guardian review keyword cloud" action={<Badge colorPalette="orange" variant="subtle">{visibleTerms.length} keywords</Badge>}>
      <Flex
        role="img"
        aria-label="Word cloud of keywords from all Guardian reviews"
        minH={{ base: "260px", md: "320px" }}
        align="center"
        justify="center"
        alignContent="center"
        gap={{ base: "2.5", md: "3.5" }}
        wrap="wrap"
        px={{ base: "1", md: "5" }}
        py={{ base: "5", md: "7" }}
        bg="subtle"
        borderRadius="control"
      >
        {visibleTerms.map((term, index) => {
          const weight = scale(term.count);
          const color = chartColors[index % chartColors.length];
          return (
            <Box
              as="span"
              key={term.keyword}
              title={`${term.keyword}: ${term.count.toLocaleString()} mentions`}
              color={color}
              fontSize={`${0.9 + weight * 2.1}rem`}
              fontWeight={Math.round(600 + weight * 200)}
              lineHeight="1"
              px="1"
              py="1.5"
              opacity={0.72 + weight * 0.28}
              whiteSpace="nowrap"
            >
              {cleanDisplayText(term.keyword)}
            </Box>
          );
        })}
      </Flex>
    </Section>
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

function combinedPeriod(product: DashboardProduct) {
  return {
    feedback: product.current.feedback + product.baseline.feedback,
    complaints: product.current.complaints + product.baseline.complaints,
    positive: product.current.positive + product.baseline.positive,
    neutral: product.current.neutral + product.baseline.neutral,
  };
}

function periodForMode(product: DashboardProduct, mode: DateMode) {
  if (mode === "all") return product.overall ?? combinedPeriod(product);
  if (mode === "current") return product.current;
  return combinedPeriod(product);
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
      minH={{ base: "104px", md: "112px" }}
      width="full"
      px={{ base: "5", md: "7" }}
      py={{ base: "4", md: "5" }}
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
        <Badge mb="2" colorPalette="orange" variant="subtle" fontSize="2xs">AI summary</Badge>
        <Heading size={{ base: "sm", md: "lg" }} lineHeight="1.28" letterSpacing="0">
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
  const [datePreset, setDatePreset] = useState<DatePreset>("all");
  const [customRange, setCustomRange] = useState({ from: "", to: "" });
  const [exportError, setExportError] = useState<string | null>(null);
  const dateMode: DateMode = datePreset === "all" ? "all" : datePreset === "7d" ? "current" : "combined";

  const totals = data.products.reduce((result, product) => {
    const period = periodForMode(product, dateMode);
    return { feedback: result.feedback + period.feedback, complaints: result.complaints + period.complaints, positive: result.positive + period.positive, neutral: result.neutral + period.neutral };
  }, { feedback: 0, complaints: 0, positive: 0, neutral: 0 });
  const negative = Math.max(0, totals.feedback - totals.positive - totals.neutral);
  const ratingCounts = new Map<number, number>([5, 4, 3, 2, 1].map((rating) => [rating, 0]));
  data.products.forEach((product) => {
    const allRatings = product.allRatingDistribution ?? [];
    const distributions = dateMode === "all"
      ? [allRatings.length ? allRatings : [...product.ratingDistribution, ...product.baselineRatingDistribution]]
      : dateMode === "current"
        ? [product.ratingDistribution]
        : [product.ratingDistribution, product.baselineRatingDistribution];
    distributions.flat().forEach((item) => ratingCounts.set(item.rating, (ratingCounts.get(item.rating) ?? 0) + item.count));
  });
  const ratingDistribution = [5, 4, 3, 2, 1].map((rating) => ({ label: String(rating), count: ratingCounts.get(rating) ?? 0 }));
  const displayedIssueCount = (item: ProductTheme) => dateMode === "current" || dateMode === "all" ? item.count : item.count + item.baselineCount;
  const periodIssueSort = (a: ProductTheme, b: ProductTheme) => displayedIssueCount(b) - displayedIssueCount(a) || a.label.localeCompare(b.label);
  const allProblems = aggregateThemes(data.products, "allProblems");
  const problems = (dateMode === "all" && allProblems.length ? allProblems : aggregateThemes(data.products, "problems")).sort(periodIssueSort).slice(0, 5);
  const ratingTrend = filterRatingTrend(aggregateRatingTrend(data.products), trendDateRange(data, datePreset, customRange));
  const insight = hasUsefulInsight(data) ? data.primaryInsight : null;
  const weeklyMessage = weeklySummaryMessage({ insight, feedback: totals.feedback, positive: totals.positive, neutral: totals.neutral, issue: problems[0] });

  const metrics = [
    { icon: <ChatCircleDots size={28} />, label: "Reviews", value: totals.feedback.toLocaleString(), iconBg: "#eff6ff", darkIconBg: "#10233f", color: "#2563eb" },
    { icon: <CheckCircle size={28} weight="fill" />, label: "Positive", value: percent(ratio(totals.positive, totals.feedback), 0), iconBg: "#ecfdf3", darkIconBg: "#102b20", color: "#16a34a" },
    { icon: <Pulse size={28} weight="fill" />, label: "Neutral", value: percent(ratio(totals.neutral, totals.feedback), 0), iconBg: "#fff7e6", darkIconBg: "#38260d", color: "#d97706" },
    { icon: <WarningCircle size={28} weight="fill" />, label: "Negative", value: percent(ratio(negative, totals.feedback), 0), iconBg: "#fff1f2", darkIconBg: "#3a151c", color: "#e11d48" },
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
        <Flex align="center" gap="3" wrap="wrap">
          <DateRangeFilter value={datePreset} onChange={setDatePreset} customRange={customRange} onCustomRangeChange={setCustomRange} />
        </Flex>
        <Flex align={{ base: "stretch", sm: "center" }} justify={{ base: "stretch", sm: "flex-end" }} direction={{ base: "column", sm: "row" }} gap="3">
          <Button
            colorPalette="orange"
            variant="outline"
            onClick={() => {
              setExportError(null);
              if (!openDashboardPdfReport(data)) setExportError("Allow pop-ups to export the PDF report.");
            }}
          >
            <DownloadSimple size={18} weight="bold" />
            Export PDF
          </Button>
        </Flex>
      </Flex>
      {exportError && <Text color="danger" fontSize="sm" role="alert">{exportError}</Text>}

      <WeeklySummaryCard message={weeklyMessage} />

      <Grid as="section" aria-label="Sentiment metrics" gridTemplateColumns={{ base: "repeat(2, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap="4">
        {metrics.map((metric) => <Flex key={metric.label} minH={{ base: "126px", md: "112px" }} p={{ base: "4", md: "4" }} gap={{ base: "2", md: "3" }} direction={{ base: "column", md: "row" }} justify={{ base: "center", md: "flex-start" }} align="center" bg="surface" borderWidth="1px" borderTopWidth="3px" borderColor="border" borderTopColor={metric.color} borderRadius="panel">
          <Flex color={metric.color} bg={metric.iconBg} _dark={{ bg: metric.darkIconBg }} w={{ base: "10", md: "11" }} h={{ base: "10", md: "11" }} borderRadius="control" align="center" justify="center" flex="0 0 auto">{metric.icon}</Flex>
          <Box minW="0" textAlign={{ base: "center", md: "left" }}><Text color="muted" fontSize="sm" fontWeight="600" whiteSpace="nowrap">{metric.label}</Text><Text fontSize={{ base: "xl", md: "2xl" }} lineHeight="1.1" fontWeight="780" letterSpacing="0" whiteSpace="nowrap">{metric.value}</Text></Box>
        </Flex>)}
      </Grid>

      <Grid gridTemplateColumns={{ base: "1fr", md: "repeat(2, minmax(0, 1fr))" }} gap="4">
        <Section title="Rating distribution"><RatingBars items={ratingDistribution} /></Section>
        <Section title="Top 5 product problems"><ProblemCategoryChart items={problems} mode={dateMode} empty="No product problems in this period." /></Section>
        <Section title="Rating trend & forecast"><RatingTrendChart points={ratingTrend} /></Section>
        <Section title="Social experience score"><SocialExperienceScore benchmark={data.benchmark} /></Section>
      </Grid>

      <GuardianWordCloud terms={data.wordCloud} />
    </Stack>
  );
}
