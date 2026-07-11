import { Badge, Box, Button, Flex, Grid, Heading, Stack, Text } from "@chakra-ui/react";
import { ArrowRight, ChatCircleDots, Package, Pulse, Star, TrendDown, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import type { DashboardData, DashboardProduct, ProductTheme } from "../api/types";
import { ProductFilter } from "./ProductFilter";

interface DashboardProps { data: DashboardData; }

function productName(product: DashboardProduct): string {
  return product.shortName ?? product.name ?? `Unidentified product - ${product.id}`;
}

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
  const counts = new Map<string, number>();
  products.forEach((product) => product[key].forEach((item) => counts.set(item.label, (counts.get(item.label) ?? 0) + item.count)));
  return [...counts.entries()].map(([label, count]) => ({ label, subtopic: null, count })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

const panelProps = { bg: "surface", borderWidth: "1px", borderColor: "border", borderRadius: "panel", p: { base: "5", md: "6" } } as const;

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Box {...panelProps}>
      <Flex align="center" justify="space-between" gap="4" mb="5">
        <Heading size="md" letterSpacing="0">{title}</Heading>
        {action}
      </Flex>
      {children}
    </Box>
  );
}

function HorizontalBars({ items, tone, empty }: { items: Array<{ label: string; count: number }>; tone: "rating" | "feedback" | "problem"; empty: string }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  const color = tone === "rating" ? "#d97706" : tone === "feedback" ? "#c2410c" : "#2563eb";
  if (!items.length) return <Text color="muted">{empty}</Text>;
  return (
    <Stack gap="3">
      {items.map((item) => (
        <Grid key={item.label} gridTemplateColumns="minmax(120px, 1fr) minmax(90px, 2fr) 52px" gap="3" alignItems="center">
          <Text fontSize="sm" fontWeight="600">{item.label}</Text>
          <Box h="8px" bg="subtle" borderRadius="full" overflow="hidden">
            <Box h="full" borderRadius="full" bg={color} width={`${Math.max(2, (item.count / max) * 100)}%`} />
          </Box>
          <Text textAlign="right" fontSize="sm" fontWeight="700">{item.count.toLocaleString()}</Text>
        </Grid>
      ))}
    </Stack>
  );
}

function hasUsefulInsight(data: DashboardData): boolean {
  if (!data.primaryInsight) return false;
  const title = data.primaryInsight.title.trim();
  return Boolean(title && !/^ai auto summary$/i.test(title));
}

export function Dashboard({ data }: DashboardProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => data.products.map((product) => product.id));
  useEffect(() => setSelectedIds(data.products.map((product) => product.id)), [data]);

  const selectedProducts = useMemo(() => data.products.filter((product) => selectedIds.includes(product.id)), [data.products, selectedIds]);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedEvidence = data.evidence.filter((item) => item.productId === null || selectedSet.has(item.productId));
  const totals = selectedProducts.reduce((result, product) => ({
    feedback: result.feedback + product.current.feedback,
    complaints: result.complaints + product.current.complaints,
    positive: result.positive + product.current.positive,
  }), { feedback: 0, complaints: 0, positive: 0 });
  const weightedRatings = selectedProducts.reduce((result, product) => ({
    total: result.total + (product.rating ?? 0) * (product.ratingCount ?? 0),
    count: result.count + (product.ratingCount ?? 0),
  }), { total: 0, count: 0 });
  const averageRating = weightedRatings.count ? weightedRatings.total / weightedRatings.count : null;
  const atRisk = selectedProducts.filter((product) => (ratio(product.current.complaints, product.current.feedback) ?? 0) >= .1 || (product.sentimentDelta ?? 0) <= -10);
  const ratingCounts = new Map<number, number>([5, 4, 3, 2, 1].map((rating) => [rating, 0]));
  selectedProducts.forEach((product) => product.ratingDistribution.forEach((item) => ratingCounts.set(item.rating, (ratingCounts.get(item.rating) ?? 0) + item.count)));
  const ratingDistribution = [5, 4, 3, 2, 1].map((rating) => ({ label: `${rating} star${rating === 1 ? "" : "s"}`, count: ratingCounts.get(rating) ?? 0 })).filter((item) => item.count > 0);
  const negativeFeedback = aggregateThemes(selectedProducts, "negativeFeedback").slice(0, 5).map((item) => ({ ...item, label: humanize(item.label) }));
  const problems = aggregateThemes(selectedProducts, "problems").slice(0, 5).map((item) => ({ ...item, label: humanize(item.label) }));
  const productsToWatch = [...selectedProducts].sort((a, b) => (ratio(b.current.complaints, b.current.feedback) ?? 0) - (ratio(a.current.complaints, a.current.feedback) ?? 0)).slice(0, 3);
  const heroProduct = productsToWatch[0];
  const insight = hasUsefulInsight(data) ? data.primaryInsight : null;

  return (
    <Stack gap="6">
      <Flex align={{ base: "stretch", md: "center" }} justify="space-between" direction={{ base: "column", md: "row" }} gap="4">
        <Flex gap="3" wrap="wrap" align="center">
          <Badge size="lg" colorPalette="orange" variant="subtle">{selectedProducts.length} products</Badge>
          <Badge size="lg" colorPalette="gray" variant="outline">{totals.feedback.toLocaleString()} feedback</Badge>
        </Flex>
        <ProductFilter products={data.products} selectedIds={selectedIds} onChange={setSelectedIds} />
      </Flex>

      {selectedProducts.length === 0 ? (
        <Stack {...panelProps} align="flex-start" gap="4">
          <Package size={28} />
          <Heading size="lg">No products selected</Heading>
          <Button colorPalette="orange" onClick={() => setSelectedIds(data.products.map((product) => product.id))}>Show products</Button>
        </Stack>
      ) : (
        <>
          {insight && (
            <Grid as="section" aria-labelledby="pulse-title" {...panelProps} bg="orange.50" _dark={{ bg: "#24150d" }} gridTemplateColumns={{ base: "1fr", md: "auto 1fr auto" }} alignItems="center" gap="5">
              <Flex w="12" h="12" align="center" justify="center" borderRadius="full" bg="orange.100" color="orange.700"><Pulse size={25} weight="fill" /></Flex>
              <Box>
                <Heading id="pulse-title" size="lg" letterSpacing="0">{insight.title}</Heading>
                {insight.summary && <Text color="muted" mt="2">{insight.summary}</Text>}
              </Box>
              {heroProduct && <Button variant="outline" colorPalette="orange" onClick={() => setSelectedIds([heroProduct.id])}>Focus <ArrowRight size={16} /></Button>}
            </Grid>
          )}

          <Grid as="section" aria-label="Portfolio metrics" gridTemplateColumns={{ base: "repeat(2, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap="4">
            {[
              [<ChatCircleDots size={22} key="i" />, "Feedback", totals.feedback.toLocaleString()],
              [<Star size={22} weight="fill" key="i" />, "Rating", averageRating === null ? "-" : `${averageRating.toFixed(2)} / 5`],
              [<TrendDown size={22} key="i" />, "Complaints", totals.complaints.toLocaleString()],
              [<WarningCircle size={22} weight="fill" key="i" />, "At risk", atRisk.length],
            ].map(([icon, label, value]) => (
              <Flex key={String(label)} {...panelProps} gap="3" align="center">
                <Box color="accent">{icon}</Box>
                <Box minW="0">
                  <Text color="muted" fontSize="sm">{label}</Text>
                  <Text fontSize={{ base: "2xl", md: "3xl" }} lineHeight="1.1" fontWeight="750" letterSpacing="0">{value}</Text>
                </Box>
              </Flex>
            ))}
          </Grid>

          <Grid gridTemplateColumns={{ base: "1fr", xl: "repeat(3, 1fr)" }} gap="4">
            <Section title="Star ratings">
              <HorizontalBars items={ratingDistribution} tone="rating" empty="No ratings returned." />
            </Section>
            <Section title="Negative topics">
              <HorizontalBars items={negativeFeedback} tone="feedback" empty="No complaint topics returned." />
            </Section>
            <Section title="Product problems">
              <HorizontalBars items={problems} tone="problem" empty="No problem topics returned." />
            </Section>
          </Grid>

          <Grid gridTemplateColumns={{ base: "1fr", xl: "1.1fr .9fr" }} gap="4">
            <Section title="Products to watch">
              <Stack gap="0" divideY="1px" divideColor="border">
                {productsToWatch.map((product, index) => (
                  <Button key={product.id} variant="ghost" h="auto" py="4" px="0" borderRadius="0" justifyContent="stretch" onClick={() => setSelectedIds([product.id])}>
                    <Grid width="full" gridTemplateColumns="32px minmax(0,1fr) auto" gap="3" textAlign="left" alignItems="center">
                      <Text color="muted" fontWeight="700">{index + 1}</Text>
                      <Box minW="0">
                        <Text fontWeight="700" whiteSpace="normal">{productName(product)}</Text>
                        <Text color="muted" fontSize="sm" whiteSpace="normal">{humanize(product.problems[0]?.label ?? "No dominant problem")}</Text>
                      </Box>
                      <Text color="danger" fontWeight="750">{percent(ratio(product.current.complaints, product.current.feedback), 0)}</Text>
                    </Grid>
                  </Button>
                ))}
              </Stack>
            </Section>

            <Section title="Benchmark">
              {!data.benchmark?.comparable ? (
                <Text color="muted">{data.benchmark?.reason ?? "Comparison not available."}</Text>
              ) : (
                <Stack gap="4">
                  {data.benchmark.brands.map((brand) => (
                    <Grid key={brand.brand} gridTemplateColumns="90px 1fr 44px" gap="3" alignItems="center">
                      <Text fontSize="sm" fontWeight="600">{humanize(brand.brand)}</Text>
                      <Box h="8px" bg="subtle" borderRadius="full" overflow="hidden">
                        <Box h="full" bg="accent" borderRadius="full" width={`${((brand.rating ?? 0) / 5) * 100}%`} />
                      </Box>
                      <Text fontWeight="700">{brand.rating === null ? "-" : brand.rating.toFixed(2)}</Text>
                    </Grid>
                  ))}
                </Stack>
              )}
            </Section>
          </Grid>

          <Section title="Evidence" action={<Badge variant="outline">{selectedEvidence.length}</Badge>}>
            {selectedEvidence.length ? (
              <Grid gridTemplateColumns={{ base: "1fr", lg: "repeat(2, 1fr)" }} gap="4">
                {selectedEvidence.slice(0, 6).map((item) => (
                  <Box as="blockquote" key={item.id} p="4" bg="subtle" borderRadius="control">
                    <Text>"{item.text}"</Text>
                    <Text as="footer" mt="3" color="muted" fontSize="sm">{item.sourcePlatform} - {humanize(item.sourceGroup)}</Text>
                  </Box>
                ))}
              </Grid>
            ) : (
              <Text color="muted">No evidence returned.</Text>
            )}
          </Section>

          {insight && insight.recommendedActions.length > 0 && (
            <Section title="Actions">
              <Stack as="ul" gap="2" pl="5" color="muted">
                {insight.recommendedActions.map((action) => <li key={action}>{action}</li>)}
              </Stack>
            </Section>
          )}
        </>
      )}
    </Stack>
  );
}
