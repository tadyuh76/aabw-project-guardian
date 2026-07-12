import { Badge, Box, Button, Flex, Grid, Heading, IconButton, Input, Spinner, Stack, Text, Tooltip } from "@chakra-ui/react";
import { ArrowRight, CalendarBlank, CaretLeft, CaretRight, ChatCircleDots, CheckCircle, DownloadSimple, Info, Package, Pulse, Sparkle, Star, WarningCircle, X } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { fetchDashboard, fetchProblemDetail, type DashboardRangePreset } from "../api/client";
import type { DashboardData, DashboardProblemDetail, DashboardProduct, ProblemBreakdown, ProductRatingTrendPoint, ProductTheme, SentimentTrendPoint } from "../api/types";
import { captureDashboardPdf } from "../utils/dashboardPdf";
import { cleanDisplayText } from "../utils/displayText";

interface DashboardProps { data: DashboardData; }
type DatePreset = DashboardRangePreset;
type DateMode = "current" | "combined" | "all";

const chartColors = ["#ec7e24", "#2563eb", "#16a34a", "#7c3aed", "#e11d48"];
const chartViewBoxWidth = 760;
const chartTextSize = 13;
const chartLabelSize = 20;
const chartValueSize = 13;
const platformColors: Record<string, string> = {
  "Guardian.com.vn": "#ec7e24",
  "TikTok Shop": "#18181b",
  Shopee: "#f97316",
  Lazada: "#7c3aed",
  GrabMart: "#16a34a",
};
const panelProps = { bg: "surface", borderWidth: "1px", borderColor: "border", borderRadius: "panel", p: { base: "4", md: "5" } } as const;
const svgChartStyle = { width: "100%", minWidth: "340px", display: "block" } as const;
const socialExperienceScoreInfo = "Score = 50 + 50 x ((positive mentions - negative mentions) / total mentions). Neutral mentions keep the score near 50, while more positive feedback moves it toward 100 and more negative feedback moves it toward 0.";

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}

function percent(value: number | null, digits = 1): string {
  return value === null ? "-" : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: digits }).format(value);
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function chartColor(index: number): string {
  return chartColors[index % chartColors.length] ?? chartColors[0]!;
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

function Section({ title, titleInfo, action, children }: { title: string; titleInfo?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Box {...panelProps} minW="0">
      <Flex align="center" justify="space-between" gap="4" mb="4">
        <Flex align="center" gap="2" minW="0">
          <Heading size="md" fontWeight="800" letterSpacing="0">{title}</Heading>
          {titleInfo && (
            <Tooltip.Root openDelay={150} positioning={{ placement: "top-start" }}>
              <Tooltip.Trigger asChild>
                <IconButton
                  aria-label={`How ${title.toLowerCase()} is calculated`}
                  size="2xs"
                  variant="ghost"
                  color="muted"
                  minW="5"
                  h="5"
                  borderRadius="full"
                >
                  <Info size={14} weight="bold" />
                </IconButton>
              </Tooltip.Trigger>
              <Tooltip.Positioner>
                <Tooltip.Content maxW="280px" p="3" fontSize="xs" lineHeight="1.45" boxShadow="lg">
                  <Tooltip.Arrow />
                  {titleInfo}
                </Tooltip.Content>
              </Tooltip.Positioner>
            </Tooltip.Root>
          )}
        </Flex>
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

function formatApiDate(date: Date): string {
  return [
    String(date.getFullYear()),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
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
  const rootRef = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [open]);

  return (
    <Box position="relative" ref={rootRef}>
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

function sentimentPeriodLabel(value: string, granularity: "day" | "month"): string {
  const date = dateOnly(value);
  if (!date) return value;
  return granularity === "day"
    ? new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(date)
    : new Intl.DateTimeFormat("en-GB", { month: "short", year: "2-digit" }).format(date);
}

function SentimentBars({ points, granularity }: { points: SentimentTrendPoint[]; granularity: "day" | "month" }) {
  const colors = { positive: "#16a34a", neutral: "#d97706", negative: "#e11d48" };
  const ariaLabel = points.map((point) => `${sentimentPeriodLabel(point.date, granularity)}: ${point.positive.toLocaleString()} positive, ${point.neutral.toLocaleString()} neutral, ${point.negative.toLocaleString()} negative`).join(". ");
  return (
    <Stack gap="4" pt="2">
      <Flex justify="flex-end" gap="4" wrap="wrap">
        <Flex align="center" gap="2"><Box w="3" h="3" bg={colors.positive} borderRadius="sm" /><Text color="muted" fontSize="xs" fontWeight="650">Positive</Text></Flex>
        <Flex align="center" gap="2"><Box w="3" h="3" bg={colors.neutral} borderRadius="sm" /><Text color="muted" fontSize="xs" fontWeight="650">Neutral</Text></Flex>
        <Flex align="center" gap="2"><Box w="3" h="3" bg={colors.negative} borderRadius="sm" /><Text color="muted" fontSize="xs" fontWeight="650">Negative</Text></Flex>
      </Flex>
      <Box overflowX="auto">
      <Flex role="img" aria-label={`Review sentiment over time. ${ariaLabel || "No sentiment data"}`} minH="220px" minW={points.length > 14 ? "720px" : "full"} gap="3">
        <Flex direction="column" justify="space-between" h="164px" pt="1" pb="1" color="muted" fontSize="2xs" textAlign="right">
          <Text>100%</Text><Text>50%</Text><Text>0%</Text>
        </Flex>
        <Box position="relative" flex="1" minW="0" h="220px">
          <Box position="absolute" left="0" right="0" top="0" h="164px">
            {[0, 50, 100].map((value) => <Box key={value} position="absolute" left="0" right="0" top={`${100 - value}%`} borderTopWidth="1px" borderColor="border" />)}
          </Box>
          <Flex position="relative" h="full" align="flex-start" justify="space-around" gap={{ base: "1", md: "2" }}>
            {points.map((point, index) => {
              const segments = [
                { label: "Negative", count: point.negative, rate: ratio(point.negative, point.total) ?? 0, color: colors.negative },
                { label: "Neutral", count: point.neutral, rate: ratio(point.neutral, point.total) ?? 0, color: colors.neutral },
                { label: "Positive", count: point.positive, rate: ratio(point.positive, point.total) ?? 0, color: colors.positive },
              ];
              return (
                <Stack key={point.date} flex="1" minW="0" gap="2" align="center">
                  <Flex h="164px" align="flex-end" justify="center" width="full" title={`${sentimentPeriodLabel(point.date, granularity)}: ${point.total.toLocaleString()} classified reviews`}>
                    <Stack h="164px" justify="flex-end" align="center" gap="1" width="full">
                      <Text fontSize="2xs" fontWeight="750">{point.total.toLocaleString()}</Text>
                      <Flex direction="column" width="full" maxW={{ base: "28px", md: "38px" }} h="124px" justify="flex-end" borderRadius="5px 5px 1px 1px" overflow="hidden">
                        {segments.map((segment) => <Box key={segment.label} width="full" h={`${segment.rate * 124}px`} minH={segment.count > 0 ? "1px" : "0"} bg={segment.color} transition="height .25s ease" />)}
                      </Flex>
                    </Stack>
                  </Flex>
                  <Text fontSize="2xs" fontWeight="700" textAlign="center" lineHeight="1.35" whiteSpace="nowrap">{granularity === "month" || index === 0 || index === points.length - 1 || index % 5 === 0 ? sentimentPeriodLabel(point.date, granularity) : "\u00a0"}</Text>
                </Stack>
              );
            })}
          </Flex>
        </Box>
      </Flex>
      </Box>
    </Stack>
  );
}

function ProblemCategoryChart({ items, mode, empty, onViewMore }: { items: ProductTheme[]; mode: DateMode; empty: string; onViewMore: (problem: string) => void }) {
  const displayed = items.map((item) => ({
    ...item,
    displayCount: mode === "current" ? item.count : item.count + item.baselineCount,
  }));
  const max = Math.max(1, ...displayed.map((item) => item.displayCount));
  if (!displayed.some((item) => item.displayCount > 0)) return <Text color="muted">{empty}</Text>;
  const width = chartViewBoxWidth;
  const rowHeight = 42;
  const top = 12;
  const right = 142;
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
              <rect x={labelWidth} y={y + 10} width={bar} height="18" rx="4" fill={chartColor(index + 1)} />
              <text x={labelWidth + bar + 10} y={y + 25} fill="var(--chakra-colors-ink)" fontSize={chartValueSize} fontWeight="750">
                {item.displayCount.toLocaleString()}
              </text>
              <g
                role="button"
                tabIndex={0}
                aria-label={`View more about ${label}`}
                onClick={() => onViewMore(item.label)}
                onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onViewMore(item.label); }}
                style={{ cursor: "pointer" }}
              >
                <text x={width - 4} y={y + 25} textAnchor="end" fill="var(--chakra-colors-accent)" fontSize={chartValueSize} fontWeight="750">
                  View more →
                </text>
              </g>
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
              <Box h="full" bg={chartColor(index)} borderRadius="full" width={`${Math.max(0, Math.min(100, score ?? 0))}%`} />
            </Box>
          </Box>
        );
      })}
    </Stack>
  );
}

function hasUsefulInsight(data: DashboardData): boolean {
  const title = data.primaryInsight?.title.trim() ?? "";
  return Boolean(title && !/^ai auto summary$/i.test(title));
}

function weeklySummaryMessage({ insight, feedback, positive, neutral, issue }: { insight: DashboardData["primaryInsight"]; feedback: number; positive: number; neutral: number; issue?: ProductTheme }): string {
  if (insight) return cleanDisplayText(insight.title);
  if (feedback <= 0) return "No resolved customer feedback in this period.";
  const negative = Math.max(0, feedback - positive - neutral);
  if (positive >= negative && issue && issue.count > 0) return `Customers are mostly happy, but ${humanize(issue.label).toLocaleLowerCase()} needs action now.`;
  if (positive >= negative) return "Customers are mostly happy in this period.";
  if (issue && issue.count > 0) return `${humanize(issue.label)} needs action in this period.`;
  return "Customer sentiment needs attention in this period.";
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

function WeeklySummaryCard({ message, isAi }: { message: string; isAi: boolean }) {
  return (
    <Flex
      as="section"
      aria-label={isAi ? "AI summary" : "Period summary"}
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
        <Badge mb="2" colorPalette="orange" variant="subtle" fontSize="2xs">{isAi ? "AI summary" : "Period summary"}</Badge>
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

function BreakdownChart({ title, items }: { title: string; items: ProblemBreakdown[] }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <Box {...panelProps} p="4">
      <Text fontWeight="750" mb="4">{title}</Text>
      {items.length ? <Stack gap="3">{items.map((item) => (
        <Box key={item.label}>
          <Flex justify="space-between" gap="3" mb="1.5"><Text fontSize="sm" fontWeight="650" lineClamp={1}>{cleanDisplayText(item.label)}</Text><Text fontSize="sm" fontWeight="750">{item.count}</Text></Flex>
          <Box h="8px" bg="subtle" borderRadius="full" overflow="hidden"><Box h="full" bg="accent" borderRadius="full" width={`${Math.max(4, item.count / max * 100)}%`} /></Box>
        </Box>
      ))}</Stack> : <Text color="muted" fontSize="sm">No breakdown is available.</Text>}
    </Box>
  );
}

function ComplaintTrendChart({ detail }: { detail: DashboardProblemDetail }) {
  const points = detail.trend;
  const max = Math.max(1, ...points.map((point) => point.count));
  return (
    <Box {...panelProps} p="4">
      <Text fontWeight="750" mb="4">Complaints over time</Text>
      {points.length ? (
        <Flex h="170px" align="flex-end" gap="1.5" role="img" aria-label="Complaint count over time">
          {points.map((point, index) => (
            <Flex key={point.date} direction="column" justify="flex-end" align="center" flex="1" minW="4px" h="full" gap="1">
              <Text fontSize="2xs" fontWeight="700">{point.count}</Text>
              <Box w="full" maxW="24px" minH="5px" h={`${Math.max(5, point.count / max * 118)}px`} bg="accent" borderRadius="4px 4px 1px 1px" title={`${point.date}: ${point.count}`} />
              {(index === 0 || index === points.length - 1) && <Text fontSize="2xs" color="muted" whiteSpace="nowrap">{new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(new Date(`${point.date}T00:00:00`))}</Text>}
            </Flex>
          ))}
        </Flex>
      ) : <Text color="muted" fontSize="sm">No dated complaints are available.</Text>}
    </Box>
  );
}

function ProblemDetailModal({ problem, preset, customRange, onClose }: { problem: string; preset: DatePreset; customRange: { from: string; to: string }; onClose: () => void }) {
  const [detail, setDetail] = useState<DashboardProblemDetail | null>(null);
  const [error, setError] = useState("");
  const parsedStart = parseDisplayDate(customRange.from);
  const parsedEnd = parseDisplayDate(customRange.to);
  const isoDate = (date: Date | null) => date ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}` : undefined;

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError("");
    void fetchProblemDetail(problem, {
      preset,
      startDate: preset === "custom" ? isoDate(parsedStart) : undefined,
      endDate: preset === "custom" ? isoDate(parsedEnd) : undefined,
    }, controller.signal).then(setDetail).catch((cause) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Problem detail could not be loaded.");
    });
    return () => controller.abort();
  }, [problem, preset, customRange.from, customRange.to]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", closeOnEscape);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", closeOnEscape); };
  }, [onClose]);

  const readableProblem = humanize(problem);
  const viewAllReviews = () => {
    const params = new URLSearchParams({ problem, timeframe: preset });
    window.history.pushState(null, "", `/reviews?${params}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
    onClose();
  };
  return (
    <Flex position="fixed" inset="0" zIndex="modal" bg="rgba(15, 23, 42, 0.56)" align={{ base: "stretch", md: "center" }} justify="center" p={{ base: "0", md: "5" }} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <Box role="dialog" aria-modal="true" aria-labelledby="problem-detail-title" bg="canvas" width="full" maxW="1180px" maxH={{ base: "100vh", md: "92vh" }} overflowY="auto" borderRadius={{ base: "0", md: "panel" }} boxShadow="2xl">
        <Flex position="sticky" top="0" zIndex="docked" bg="surface" borderBottomWidth="1px" borderColor="border" px={{ base: "4", md: "6" }} py="4" align="flex-start" justify="space-between" gap="4">
          <Box><Heading id="problem-detail-title" size="lg">{readableProblem}</Heading><Text color="muted" fontSize="sm">{detail?.periodLabel ?? "Loading complaint cohort..."}</Text></Box>
          <Button variant="ghost" size="sm" aria-label="Close problem detail" onClick={onClose}><X size={20} /></Button>
        </Flex>
        <Stack p={{ base: "4", md: "6" }} gap="5">
          {error ? <Box {...panelProps} role="alert"><Heading size="sm" mb="2">Problem detail could not be loaded</Heading><Text color="muted">{error}</Text></Box> : !detail ? <Flex minH="360px" align="center" justify="center" gap="3"><Spinner color="accent" /><Text color="muted">Analyzing complaint evidence...</Text></Flex> : <>
            <Grid gridTemplateColumns={{ base: "1fr", md: "repeat(3, minmax(0, 1fr))" }} gap="3">
              {[
                [detail.count.toLocaleString(), "Complaints"],
                [detail.share === null ? "-" : percent(detail.share, 0), "Share of complaints"],
                [detail.percentageChange === null ? "-" : `${detail.percentageChange >= 0 ? "+" : ""}${detail.percentageChange.toFixed(0)}%`, "Vs previous period"],
              ].map(([value, label]) => <Box key={label} {...panelProps} p="4"><Text fontSize="2xl" fontWeight="780">{value}</Text><Text color="muted" fontSize="sm">{label}</Text></Box>)}
            </Grid>
            <Box {...panelProps} borderColor="brand.200" bg="surface">
	              <Flex align="center" gap="2" mb="3"><Sparkle size={20} weight="fill" color="var(--chakra-colors-accent)" /><Text fontWeight="780">{detail.summarySource === "ai" ? "AI summary" : "Evidence summary"}</Text>{detail.summarySource === "ai" && <Badge colorPalette="orange" variant="subtle">{detail.summaryModel ?? "GPT"}</Badge>}</Flex>
              <Text lineHeight="1.7">{cleanDisplayText(detail.summary)}</Text>
              <Text mt="3" color="muted" fontSize="xs">Based on {detail.count.toLocaleString()} complaint{detail.count === 1 ? "" : "s"} in this cohort.</Text>
              {detail.themes.length > 0 && <Flex mt="4" gap="2" wrap="wrap">{detail.themes.map((theme) => <Badge key={theme.label} colorPalette="orange" variant="subtle" px="3" py="1.5">{cleanDisplayText(theme.label)} · {theme.count}</Badge>)}</Flex>}
            </Box>
            <Grid gridTemplateColumns={{ base: "1fr", lg: "repeat(3, minmax(0, 1fr))" }} gap="4">
              <ComplaintTrendChart detail={detail} />
              <BreakdownChart title="Affected products" items={detail.products} />
              <BreakdownChart title="Source breakdown" items={detail.sources} />
            </Grid>
            <Box {...panelProps} p="0" overflow="hidden">
              <Flex px="5" py="4" align="center" justify="space-between" borderBottomWidth="1px" borderColor="border"><Text fontWeight="780">Representative reviews</Text><Text color="muted" fontSize="sm">Showing {Math.min(5, detail.reviews.length)} of {detail.count}</Text></Flex>
              {detail.reviews.length ? <Stack gap="0">{detail.reviews.slice(0, 5).map((review) => <Box key={review.id} px="5" py="4" borderTopWidth="1px" borderColor="border" _first={{ borderTopWidth: "0" }}>
                <Flex justify="space-between" gap="4" mb="2" wrap="wrap"><Text fontWeight="700">{cleanDisplayText(review.productName)}</Text><Text color="muted" fontSize="sm">{humanize(review.sourcePlatform)}{review.rating === null ? "" : ` · ${review.rating.toFixed(0)}★`}</Text></Flex>
                <Text color="ink" lineClamp={3}>{cleanDisplayText(review.text)}</Text>
              </Box>)}</Stack> : <Text p="5" color="muted">No representative reviews are available.</Text>}
            </Box>
            <Flex justify="flex-end"><Button colorPalette="orange" onClick={viewAllReviews}>View all {detail.count.toLocaleString()} reviews <ArrowRight size={18} /></Button></Flex>
          </>}
        </Stack>
      </Box>
    </Flex>
  );
}

export function Dashboard({ data }: DashboardProps) {
  const [datePreset, setDatePreset] = useState<DatePreset>("all");
  const [customRange, setCustomRange] = useState({ from: "", to: "" });
  const [rangeData, setRangeData] = useState<DashboardData>(data);
  const [rangeLoading, setRangeLoading] = useState(false);
  const [rangeError, setRangeError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [selectedProblem, setSelectedProblem] = useState<string | null>(null);
  const dashboardCaptureRef = useRef<HTMLDivElement>(null);
  const rangeRequestRef = useRef<AbortController | null>(null);
  const activeData = datePreset === "all" ? data : rangeData;
  const displayedData = activeData;
  const dateMode: DateMode = datePreset === "all" ? "all" : "current";

  useEffect(() => {
    if (datePreset === "all") {
      rangeRequestRef.current?.abort();
      setRangeData(data);
      setRangeError(null);
      setRangeLoading(false);
    }
  }, [data, datePreset]);

  useEffect(() => {
    if (datePreset === "all") return undefined;
    const from = customRange.from ? parseDisplayDate(customRange.from) : null;
    const to = customRange.to ? parseDisplayDate(customRange.to) : null;
    if (datePreset === "custom" && (!from || !to || to < from)) {
      setRangeError("Choose a valid custom date range.");
      setRangeLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    rangeRequestRef.current?.abort();
    rangeRequestRef.current = controller;
    setRangeLoading(true);
    setRangeError(null);
    void fetchDashboard(controller.signal, {
      range: datePreset,
      dateFrom: from ? formatApiDate(from) : null,
      dateTo: to ? formatApiDate(to) : null,
    }).then((nextData) => {
      if (!controller.signal.aborted) setRangeData(nextData);
    }).catch((cause) => {
      if (!controller.signal.aborted) {
        setRangeError(cause instanceof Error ? cause.message : "The dashboard range could not be loaded.");
      }
    }).finally(() => {
      if (!controller.signal.aborted) setRangeLoading(false);
    });
    return () => controller.abort();
  }, [customRange.from, customRange.to, datePreset, data.lastUpdated]);

  const totals = activeData.products.reduce((result, product) => {
    const period = periodForMode(product, dateMode);
    return { feedback: result.feedback + period.feedback, complaints: result.complaints + period.complaints, positive: result.positive + period.positive, neutral: result.neutral + period.neutral };
  }, { feedback: 0, complaints: 0, positive: 0, neutral: 0 });
  const negative = Math.max(0, totals.feedback - totals.positive - totals.neutral);
  const displayedIssueCount = (item: ProductTheme) => dateMode === "current" || dateMode === "all" ? item.count : item.count + item.baselineCount;
  const periodIssueSort = (a: ProductTheme, b: ProductTheme) => displayedIssueCount(b) - displayedIssueCount(a) || a.label.localeCompare(b.label);
  const allProblems = aggregateThemes(activeData.products, "allProblems");
  const problems = (dateMode === "all" && allProblems.length ? allProblems : aggregateThemes(activeData.products, "problems")).sort(periodIssueSort).slice(0, 5);
  const ratingTrend = filterRatingTrend(aggregateRatingTrend(activeData.products), trendDateRange(activeData, datePreset, customRange));
  const insight = datePreset === "all" && hasUsefulInsight(activeData) ? activeData.primaryInsight : null;
  const weeklyMessage = weeklySummaryMessage({ insight, feedback: totals.feedback, positive: totals.positive, neutral: totals.neutral, issue: problems[0] });

  const metrics = [
    { icon: <ChatCircleDots size={28} />, label: "Reviews", value: totals.feedback.toLocaleString(), iconBg: "#eff6ff", darkIconBg: "#10233f", color: "#2563eb" },
    { icon: <CheckCircle size={28} weight="fill" />, label: "Positive", value: percent(ratio(totals.positive, totals.feedback), 0), iconBg: "#ecfdf3", darkIconBg: "#102b20", color: "#16a34a" },
    { icon: <Pulse size={28} weight="fill" />, label: "Neutral", value: percent(ratio(totals.neutral, totals.feedback), 0), iconBg: "#fff7e6", darkIconBg: "#38260d", color: "#d97706" },
    { icon: <WarningCircle size={28} weight="fill" />, label: "Negative", value: percent(ratio(negative, totals.feedback), 0), iconBg: "#fff1f2", darkIconBg: "#3a151c", color: "#e11d48" },
  ];
  const exportDashboard = async () => {
    if (!dashboardCaptureRef.current) {
      setExportError("Dashboard is not ready to export yet.");
      return;
    }
    setExportError(null);
    setExporting(true);
    try {
      await captureDashboardPdf(dashboardCaptureRef.current, { filename: `guardian-dashboard-${datePreset}.pdf` });
    } catch {
      setExportError("Dashboard PDF could not be created. Try again after the charts finish loading.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <Stack ref={dashboardCaptureRef} data-pdf-capture="dashboard" gap="5">
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
            data-pdf-hidden="true"
            colorPalette="orange"
            variant="outline"
            disabled={exporting}
            onClick={() => void exportDashboard()}
          >
            <DownloadSimple size={18} weight="bold" />
            {exporting ? "Exporting..." : "Export PDF"}
          </Button>
        </Flex>
      </Flex>
      {rangeLoading && <Text color="muted" fontSize="sm" aria-live="polite">Updating dashboard range...</Text>}
      {rangeError && <Text color="danger" fontSize="sm" role="alert">{rangeError}</Text>}
      {exportError && <Text color="danger" fontSize="sm" role="alert">{exportError}</Text>}

      <WeeklySummaryCard message={weeklyMessage} isAi={insight !== null} />

      <Grid as="section" aria-label="Sentiment metrics" gridTemplateColumns={{ base: "repeat(2, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap="4">
        {metrics.map((metric) => <Flex key={metric.label} minH={{ base: "126px", md: "112px" }} p={{ base: "4", md: "4" }} gap={{ base: "2", md: "3" }} direction={{ base: "column", md: "row" }} justify={{ base: "center", md: "flex-start" }} align="center" bg="surface" borderWidth="1px" borderTopWidth="3px" borderColor="border" borderTopColor={metric.color} borderRadius="panel">
          <Flex color={metric.color} bg={metric.iconBg} _dark={{ bg: metric.darkIconBg }} w={{ base: "10", md: "11" }} h={{ base: "10", md: "11" }} borderRadius="control" align="center" justify="center" flex="0 0 auto">{metric.icon}</Flex>
          <Box minW="0" textAlign={{ base: "center", md: "left" }}><Text color="muted" fontSize="sm" fontWeight="600" whiteSpace="nowrap">{metric.label}</Text><Text fontSize={{ base: "xl", md: "2xl" }} lineHeight="1.1" fontWeight="780" letterSpacing="0" whiteSpace="nowrap">{metric.value}</Text></Box>
        </Flex>)}
      </Grid>

      <Grid gridTemplateColumns={{ base: "1fr", md: "repeat(2, minmax(0, 1fr))" }} gap="4">
        <Section title="Review sentiment over time"><SentimentBars points={displayedData.sentimentTrend} granularity={displayedData.sentimentTrendGranularity} /></Section>
        <Section title="Top 5 product problems"><ProblemCategoryChart items={problems} mode={dateMode} empty="No product problems in this period." onViewMore={setSelectedProblem} /></Section>
        <Section title="Rating trend & forecast"><RatingTrendChart points={ratingTrend} /></Section>
        <Section title="Social experience score" titleInfo={socialExperienceScoreInfo}><SocialExperienceScore benchmark={activeData.benchmark} /></Section>

      </Grid>
      {selectedProblem && <ProblemDetailModal problem={selectedProblem} preset={datePreset} customRange={customRange} onClose={() => setSelectedProblem(null)} />}
    </Stack>
  );
}
