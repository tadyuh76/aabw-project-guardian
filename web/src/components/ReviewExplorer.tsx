import { Badge, Box, createListCollection, Flex, Grid, Heading, Input, Select, Stack, Text } from "@chakra-ui/react";
import { FunnelSimple, MagnifyingGlass } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import type { DashboardData, DashboardEvidence } from "../api/types";
import { cleanDisplayText } from "../utils/displayText";

interface ReviewExplorerProps {
  data: DashboardData;
}

type TimeFrame = "all" | "7d" | "30d" | "90d" | "1y";
type SortMode = "newest" | "oldest" | "platform" | "problem" | "sentiment" | "product";
type ProblemCategory =
  | "Leaking"
  | "Poor packaging"
  | "Seal quality"
  | "Product leakage"
  | "Wrong item received"
  | "Broken cap"
  | "Delivery damage"
  | "Packaging deformation"
  | "Late delivery"
  | "Skin irritation";

const panelProps = { bg: "surface", borderWidth: "1px", borderColor: "border", borderRadius: "panel", p: { base: "5", md: "6" } } as const;

const timeFrames: Array<{ value: TimeFrame; label: string; days: number | null }> = [
  { value: "all", label: "All time", days: null },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
  { value: "90d", label: "Last 90 days", days: 90 },
  { value: "1y", label: "Last year", days: 365 },
];

const sortOptions: Array<{ value: SortMode; label: string }> = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "platform", label: "Platform A-Z" },
  { value: "problem", label: "Problem A-Z" },
  { value: "sentiment", label: "Sentiment" },
  { value: "product", label: "Product A-Z" },
];

const problemMatchers: Array<{ category: ProblemCategory; patterns: RegExp[] }> = [
  { category: "Wrong item received", patterns: [/wrong\s+(item|product)/i, /incorrect\s+(item|product)/i, /received\s+wrong/i] },
  { category: "Broken cap", patterns: [/broken\s+cap/i, /cap\s+(is\s+)?broken/i, /cracked\s+cap/i, /damaged\s+cap/i] },
  { category: "Late delivery", patterns: [/late\s+delivery/i, /delivery\s+(was\s+)?late/i, /\bdelayed\b/i, /slow\s+delivery/i] },
  { category: "Skin irritation", patterns: [/\birritat/i, /\brash\b/i, /\bbreakout/i, /\ballerg/i, /\bsting/i, /\bburning\b/i] },
  { category: "Product leakage", patterns: [/product\s+leak/i, /leak(?:ed|ing)?\s+(product|bottle|inside|out)/i, /\bspill(?:ed|ing)?\b/i] },
  { category: "Leaking", patterns: [/\bleak(?:ed|ing|s)?\b/i] },
  { category: "Seal quality", patterns: [/\bseal(?:ed|ing)?\b/i, /tamper/i, /safety\s+seal/i] },
  { category: "Delivery damage", patterns: [/delivery\s+damage/i, /shipping\s+damage/i, /damaged\s+(during\s+)?delivery/i, /arrived\s+damaged/i] },
  { category: "Packaging deformation", patterns: [/\bdeform/i, /\bdent(?:ed)?\b/i, /\bcrush(?:ed)?\b/i, /box\s+(was\s+)?bent/i] },
  { category: "Poor packaging", patterns: [/poor\s+packaging/i, /bad\s+packaging/i, /pack(?:ed|aging)\s+poorly/i, /\bpackaging\b/i] },
];

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function friendlyPlatform(value: string): string {
  const normalized = value.trim().toLocaleLowerCase();
  const labels: Record<string, string> = {
    guardian_ecommerce: "Guardian eCommerce",
    guardian: "Guardian",
    tiktok_shop: "TikTok Shop",
    tiktok: "TikTok",
    grabmart: "GrabMart",
    shopee: "Shopee",
    lazada: "Lazada",
    watsons: "Watsons",
    hasaki: "Hasaki",
    facebook: "Facebook",
    instagram: "Instagram",
    youtube: "YouTube",
  };
  return labels[normalized] ?? humanize(cleanDisplayText(value));
}

function friendlySourceGroup(value: string): string | null {
  const normalized = value.trim().toLocaleLowerCase();
  if (normalized === "owned" || normalized === "social") return null;
  const labels: Record<string, string> = {
    marketplace: "Marketplace",
    customer_service: "Customer service",
    public_social: "Social media",
  };
  return labels[normalized] ?? humanize(cleanDisplayText(value));
}

function parseTime(value: string | null): number | null {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : null;
}

function formatDate(value: string | null): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function sentimentPalette(sentiment: string | null): "green" | "red" | "gray" | "orange" {
  if (sentiment === "positive") return "green";
  if (sentiment === "negative") return "red";
  if (sentiment === "neutral") return "gray";
  return "orange";
}

function problemPalette(problem: ProblemCategory): "red" | "orange" | "yellow" | "purple" | "blue" | "pink" {
  if (problem === "Leaking" || problem === "Product leakage") return "red";
  if (problem === "Poor packaging" || problem === "Packaging deformation") return "orange";
  if (problem === "Seal quality" || problem === "Broken cap") return "yellow";
  if (problem === "Wrong item received") return "purple";
  if (problem === "Delivery damage" || problem === "Late delivery") return "blue";
  return "pink";
}

function FilterSelect<T extends string>({ label, value, items, onChange }: { label: string; value: T; items: Array<{ value: T; label: string }>; onChange: (value: T) => void }) {
  const collection = useMemo(() => createListCollection({ items }), [items]);
  return (
    <Select.Root
      collection={collection}
      value={[value]}
      onValueChange={(details) => {
        const next = details.value[0];
        if (next) onChange(next as T);
      }}
      minW={{ base: "full", sm: "190px" }}
      positioning={{ sameWidth: true }}
    >
      <Select.Label className="visually-hidden">{label}</Select.Label>
      <Select.HiddenSelect aria-label={label} />
      <Select.Control>
        <Select.Trigger h="42px" px="3" borderWidth="1px" borderColor="border" borderRadius="control" bg="surface" color="ink" fontWeight="650" justifyContent="space-between">
          <Select.ValueText />
          <Select.Indicator />
        </Select.Trigger>
      </Select.Control>
      <Select.Positioner>
        <Select.Content bg="surface" borderWidth="1px" borderColor="border" borderRadius="control" boxShadow="lg" zIndex="popover">
          {items.map((item) => (
            <Select.Item key={item.value} item={item} px="3" py="2.5" cursor="pointer" _highlighted={{ bg: "subtle" }}>
              <Select.ItemText>{item.label}</Select.ItemText>
              <Select.ItemIndicator />
            </Select.Item>
          ))}
        </Select.Content>
      </Select.Positioner>
    </Select.Root>
  );
}

function reviewSearchText(item: DashboardEvidence, productName: string): string {
  const problem = categorizeProblem(item);
  return [
    item.text,
    item.sourcePlatform,
    friendlyPlatform(item.sourcePlatform),
    item.sourceGroup,
    friendlySourceGroup(item.sourceGroup),
    productName,
    problem,
    item.sentiment,
    item.topic,
    item.subtopic,
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function categorizeProblem(item: DashboardEvidence): ProblemCategory {
  const source = [item.topic, item.subtopic, item.text].filter(Boolean).join(" ");
  return problemMatchers.find((matcher) => matcher.patterns.some((pattern) => pattern.test(source)))?.category ?? "Poor packaging";
}

function isSocialSource(item: DashboardEvidence): boolean {
  const group = item.sourceGroup.toLocaleLowerCase();
  const platform = item.sourcePlatform.toLocaleLowerCase();
  return group === "social" || ["facebook", "instagram", "tiktok", "youtube"].some((name) => platform === name);
}

function SourceLink({ href, children }: { href: string | null; children: ReactNode }) {
  if (!href) return <>{children}</>;
  return (
    <Box asChild color="ink" _hover={{ color: "accent", textDecoration: "underline" }}>
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    </Box>
  );
}

export function ReviewExplorer({ data }: ReviewExplorerProps) {
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("all");
  const [timeFrame, setTimeFrame] = useState<TimeFrame>("all");
  const [sortMode, setSortMode] = useState<SortMode>("newest");

  const productsById = useMemo(() => new Map(data.products.map((product) => [product.id, product])), [data.products]);
  const platforms = useMemo(
    () => [...new Set(data.evidence.map((item) => item.sourcePlatform).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    [data.evidence],
  );
  const platformOptions = useMemo(
    () => [{ value: "all", label: "All platforms" }, ...platforms.map((value) => ({ value, label: friendlyPlatform(value) }))],
    [platforms],
  );
  const anchorTime = parseTime(data.asOf) ?? parseTime(data.lastUpdated) ?? Date.now();
  const frame = timeFrames.find((item) => item.value === timeFrame) ?? timeFrames[0]!;
  const normalizedQuery = query.trim().toLocaleLowerCase();

  const reviews = useMemo(() => {
    const minimumTime = frame.days === null ? null : anchorTime - frame.days * 24 * 60 * 60 * 1000;
    return data.evidence
      .filter((item) => platform === "all" || item.sourcePlatform === platform)
      .filter((item) => {
        if (minimumTime === null) return true;
        const time = parseTime(item.timestamp);
        return time !== null && time >= minimumTime;
      })
      .filter((item) => {
        if (!normalizedQuery) return true;
        const productName = item.productId ? productsById.get(item.productId)?.name ?? "" : "";
        return reviewSearchText(item, productName).includes(normalizedQuery);
      })
      .sort((a, b) => {
        const aTime = parseTime(a.timestamp) ?? 0;
        const bTime = parseTime(b.timestamp) ?? 0;
        if (sortMode === "newest") return bTime - aTime || a.id.localeCompare(b.id);
        if (sortMode === "oldest") return aTime - bTime || a.id.localeCompare(b.id);
        if (sortMode === "platform") return a.sourcePlatform.localeCompare(b.sourcePlatform) || bTime - aTime;
        if (sortMode === "problem") return categorizeProblem(a).localeCompare(categorizeProblem(b)) || bTime - aTime;
        if (sortMode === "sentiment") return (a.sentiment ?? "").localeCompare(b.sentiment ?? "") || bTime - aTime;
        const aProduct = a.productId ? productsById.get(a.productId)?.name ?? "" : "";
        const bProduct = b.productId ? productsById.get(b.productId)?.name ?? "" : "";
        return aProduct.localeCompare(bProduct) || bTime - aTime;
      });
  }, [anchorTime, data.evidence, frame.days, normalizedQuery, platform, productsById, sortMode]);

  return (
    <Stack as="section" aria-labelledby="reviews-title" gap="6" w="full">
      <Flex align={{ base: "flex-start", md: "center" }} justify="space-between" gap="4" direction={{ base: "column", md: "row" }}>
        <Box>
          <Heading id="reviews-title" size="xl" letterSpacing="0">Reviews</Heading>
          <Text color="muted" fontSize="sm">Search and inspect customer review signals across every connected platform.</Text>
        </Box>
        <Badge colorPalette="orange" variant="subtle" px="3" py="1.5" borderRadius="control">{reviews.length.toLocaleString()} reviews</Badge>
      </Flex>

      <Box {...panelProps}>
        <Grid gridTemplateColumns={{ base: "1fr", lg: "minmax(260px, 1fr) auto auto auto" }} gap="3" alignItems="center">
          <Flex align="center" gap="2" h="42px" px="3" borderWidth="1px" borderColor="border" borderRadius="control" bg="surface">
            <MagnifyingGlass size={18} />
            <Input aria-label="Search reviews" placeholder="Search review text, product, topic..." value={query} onChange={(event) => setQuery(event.target.value)} border="0" px="0" h="38px" _focusVisible={{ outline: "none", boxShadow: "none" }} />
          </Flex>
          <FilterSelect label="Filter reviews by platform" value={platform} items={platformOptions} onChange={setPlatform} />
          <FilterSelect label="Filter reviews by time frame" value={timeFrame} items={timeFrames} onChange={setTimeFrame} />
          <FilterSelect label="Sort reviews" value={sortMode} items={sortOptions} onChange={setSortMode} />
        </Grid>
      </Box>

      <Box {...panelProps} p="0" overflow="hidden">
        {reviews.length === 0 ? (
          <Stack align="center" justify="center" minH="260px" gap="3" p="8" textAlign="center">
            <FunnelSimple size={32} />
            <Heading size="md">No reviews match these filters</Heading>
            <Text color="muted">Clear the search or expand the platform and time-frame filters.</Text>
          </Stack>
        ) : (
          <Box overflowX="auto">
              <Box as="table" width="full" minW="860px" borderCollapse="collapse" fontSize="sm">
              <Box as="thead" bg="subtle">
                <Box as="tr">
                  {["Review", "Problem", "Product", "Platform", "Sentiment", "Date"].map((label) => (
                    <Box as="th" key={label} px="3" py="2.5" textAlign="left" fontSize="xs" color="muted" fontWeight="750" textTransform="uppercase" letterSpacing="0.04em">{label}</Box>
                  ))}
                </Box>
              </Box>
              <Box as="tbody">
                {reviews.map((item) => {
                  const product = item.productId ? productsById.get(item.productId) : undefined;
                  const social = isSocialSource(item);
                  const sourceGroup = friendlySourceGroup(item.sourceGroup);
                  const problem = categorizeProblem(item);
                  return (
                    <Box as="tr" key={item.id} borderTopWidth="1px" borderColor="border">
                      <Box as="td" px="3" py="3" maxW="430px">
                        <SourceLink href={item.sourceUrl}>
                          <Text as="span" fontWeight="600" lineClamp={3} fontSize="sm">{cleanDisplayText(item.text)}</Text>
                        </SourceLink>
                      </Box>
                      <Box as="td" px="3" py="3">
                        <Badge colorPalette={problemPalette(problem)} variant="subtle" borderRadius="control" px="2.5" py="1" fontSize="xs" fontWeight="700">
                          {problem}
                        </Badge>
                      </Box>
                      <Box as="td" px="3" py="3">
                        {social ? (
                          <Text color="muted" fontSize="sm">Null</Text>
                        ) : (
                          <>
                            <SourceLink href={item.sourceUrl}>
                              <Text as="span" fontWeight="600" fontSize="sm">{cleanDisplayText(product?.shortName ?? product?.name ?? "Unknown product")}</Text>
                            </SourceLink>
                            {product?.sku && <Text color="muted" fontSize="xs">{product.sku}</Text>}
                          </>
                        )}
                      </Box>
                      <Box as="td" px="3" py="3"><Text fontSize="sm">{friendlyPlatform(item.sourcePlatform)}</Text>{sourceGroup && <Text color="muted" fontSize="xs">{sourceGroup}</Text>}</Box>
                      <Box as="td" px="3" py="3"><Badge colorPalette={sentimentPalette(item.sentiment)} variant="subtle" fontSize="xs">{humanize(cleanDisplayText(item.sentiment ?? "unknown"))}</Badge></Box>
                      <Box as="td" px="3" py="3"><Text fontSize="sm">{formatDate(item.timestamp)}</Text></Box>
                    </Box>
                  );
                })}
              </Box>
            </Box>
          </Box>
        )}
      </Box>
    </Stack>
  );
}
