export const PRODUCT_IDS = [
  "P-UV01",
  "P-UV02",
  "P-CL01",
  "P-MO01",
  "P-SE01",
  "P-TO01",
  "P-MS01",
  "P-SH01",
  "P-CD01",
  "P-BW01",
  "P-AC01",
  "P-LP01",
] as const;

export type ProductId = (typeof PRODUCT_IDS)[number];

export type Product = {
  id: ProductId;
  name: string;
  shortName: string;
  sku: string;
  category: string;
  pack: string;
  rating: number;
  ratingCount: number;
  current: { complaints: number; reviews: number };
  baseline: { complaints: number; reviews: number };
  sentimentDelta: number;
  competitors: {
    hasaki: { complaints: number; reviews: number };
    watsons: { complaints: number; reviews: number };
  };
  sources: Record<SourceKey, number>;
  themes: Array<{ label: string; count: number }>;
};

export type SourceKey = "app" | "marketplace" | "service" | "social";

export const SOURCE_LABELS: Record<SourceKey, string> = {
  app: "Guardian App",
  marketplace: "Marketplace",
  service: "Customer service",
  social: "Social / community",
};

export const PRODUCTS: Product[] = [
  {
    id: "P-UV01",
    name: "SunShield Daily SPF 50",
    shortName: "SunShield SPF 50",
    sku: "GDN-SUN-001",
    category: "Sunscreen",
    pack: "Pump · 50 ml",
    rating: 4.1,
    ratingCount: 8420,
    current: { complaints: 126, reviews: 480 },
    baseline: { complaints: 640, reviews: 16800 },
    sentimentDelta: -18,
    competitors: {
      hasaki: { complaints: 32, reviews: 690 },
      watsons: { complaints: 26, reviews: 640 },
    },
    sources: { app: 34, marketplace: 48, service: 28, social: 16 },
    themes: [
      { label: "Leaking", count: 68 },
      { label: "Broken cap", count: 36 },
      { label: "Poor packaging", count: 22 },
    ],
  },
  {
    id: "P-UV02",
    name: "UV Defense Aqua SPF 50+",
    shortName: "UV Defense SPF 50+",
    sku: "GDN-SUN-002",
    category: "Sunscreen",
    pack: "Pump · 50 ml",
    rating: 4.2,
    ratingCount: 7380,
    current: { complaints: 104, reviews: 440 },
    baseline: { complaints: 510, reviews: 14300 },
    sentimentDelta: -15,
    competitors: {
      hasaki: { complaints: 29, reviews: 650 },
      watsons: { complaints: 24, reviews: 610 },
    },
    sources: { app: 32, marketplace: 38, service: 21, social: 13 },
    themes: [
      { label: "Leaking", count: 55 },
      { label: "Broken cap", count: 31 },
      { label: "Poor packaging", count: 18 },
    ],
  },
  {
    id: "P-CL01",
    name: "PureBalance pH 5.5 Cleanser",
    shortName: "PureBalance Cleanser",
    sku: "GDN-CLN-014",
    category: "Cleanser",
    pack: "Tube · 150 ml",
    rating: 4.7,
    ratingCount: 9120,
    current: { complaints: 12, reviews: 610 },
    baseline: { complaints: 420, reviews: 19800 },
    sentimentDelta: -4,
    competitors: {
      hasaki: { complaints: 12, reviews: 580 },
      watsons: { complaints: 10, reviews: 550 },
    },
    sources: { app: 4, marketplace: 5, service: 1, social: 2 },
    themes: [
      { label: "Cracked cap", count: 7 },
      { label: "Poor packaging", count: 5 },
    ],
  },
  {
    id: "P-MO01",
    name: "Barrier Rescue Ceramide Cream",
    shortName: "Barrier Rescue Cream",
    sku: "GDN-MOI-021",
    category: "Moisturizer",
    pack: "Jar · 50 ml",
    rating: 4.6,
    ratingCount: 6260,
    current: { complaints: 18, reviews: 520 },
    baseline: { complaints: 315, reviews: 12500 },
    sentimentDelta: -3,
    competitors: {
      hasaki: { complaints: 15, reviews: 500 },
      watsons: { complaints: 13, reviews: 470 },
    },
    sources: { app: 5, marketplace: 7, service: 4, social: 2 },
    themes: [
      { label: "Broken seal", count: 11 },
      { label: "Poor packaging", count: 7 },
    ],
  },
  {
    id: "P-SE01",
    name: "Radiance C15 Serum",
    shortName: "Radiance C15 Serum",
    sku: "GDN-SER-008",
    category: "Serum",
    pack: "Dropper · 30 ml",
    rating: 4.5,
    ratingCount: 5110,
    current: { complaints: 6, reviews: 430 },
    baseline: { complaints: 190, reviews: 10400 },
    sentimentDelta: 2,
    competitors: {
      hasaki: { complaints: 8, reviews: 420 },
      watsons: { complaints: 7, reviews: 400 },
    },
    sources: { app: 2, marketplace: 2, service: 1, social: 1 },
    themes: [{ label: "Loose dropper", count: 6 }],
  },
  {
    id: "P-TO01",
    name: "Calm Reset Hydrating Toner",
    shortName: "Calm Reset Toner",
    sku: "GDN-TON-006",
    category: "Toner",
    pack: "Bottle · 200 ml",
    rating: 4.6,
    ratingCount: 4910,
    current: { complaints: 11, reviews: 460 },
    baseline: { complaints: 230, reviews: 11200 },
    sentimentDelta: 1,
    competitors: { hasaki: { complaints: 10, reviews: 450 }, watsons: { complaints: 9, reviews: 430 } },
    sources: { app: 3, marketplace: 4, service: 2, social: 2 },
    themes: [{ label: "Loose cap", count: 7 }, { label: "Strong scent", count: 4 }],
  },
  {
    id: "P-MS01",
    name: "Micellar Comfort Cleansing Water",
    shortName: "Micellar Comfort Water",
    sku: "GDN-CLN-019",
    category: "Cleanser",
    pack: "Bottle · 400 ml",
    rating: 4.8,
    ratingCount: 6880,
    current: { complaints: 13, reviews: 590 },
    baseline: { complaints: 390, reviews: 17600 },
    sentimentDelta: 3,
    competitors: { hasaki: { complaints: 12, reviews: 560 }, watsons: { complaints: 11, reviews: 540 } },
    sources: { app: 4, marketplace: 5, service: 2, social: 2 },
    themes: [{ label: "Leaking cap", count: 8 }, { label: "Eye irritation", count: 5 }],
  },
  {
    id: "P-SH01",
    name: "Daily Balance Scalp Shampoo",
    shortName: "Daily Balance Shampoo",
    sku: "GDN-HAR-012",
    category: "Hair care",
    pack: "Pump · 500 ml",
    rating: 4.5,
    ratingCount: 5540,
    current: { complaints: 16, reviews: 680 },
    baseline: { complaints: 370, reviews: 15400 },
    sentimentDelta: 2,
    competitors: { hasaki: { complaints: 14, reviews: 630 }, watsons: { complaints: 13, reviews: 610 } },
    sources: { app: 5, marketplace: 6, service: 3, social: 2 },
    themes: [{ label: "Pump stuck", count: 9 }, { label: "Dry scalp", count: 7 }],
  },
  {
    id: "P-CD01",
    name: "Silk Repair Daily Conditioner",
    shortName: "Silk Repair Conditioner",
    sku: "GDN-HAR-013",
    category: "Hair care",
    pack: "Tube · 350 ml",
    rating: 4.4,
    ratingCount: 4270,
    current: { complaints: 9, reviews: 410 },
    baseline: { complaints: 220, reviews: 9800 },
    sentimentDelta: 1,
    competitors: { hasaki: { complaints: 9, reviews: 400 }, watsons: { complaints: 8, reviews: 390 } },
    sources: { app: 3, marketplace: 3, service: 2, social: 1 },
    themes: [{ label: "Tube split", count: 5 }, { label: "Heavy texture", count: 4 }],
  },
  {
    id: "P-BW01",
    name: "Fresh Aloe Gentle Body Wash",
    shortName: "Fresh Aloe Body Wash",
    sku: "GDN-BDY-024",
    category: "Body care",
    pack: "Pump · 600 ml",
    rating: 4.6,
    ratingCount: 4380,
    current: { complaints: 10, reviews: 450 },
    baseline: { complaints: 240, reviews: 10300 },
    sentimentDelta: 2,
    competitors: { hasaki: { complaints: 10, reviews: 430 }, watsons: { complaints: 9, reviews: 420 } },
    sources: { app: 3, marketplace: 4, service: 2, social: 1 },
    themes: [{ label: "Pump damaged", count: 6 }, { label: "Weak scent", count: 4 }],
  },
  {
    id: "P-AC01",
    name: "Clear Spot Hydrocolloid Patches",
    shortName: "Clear Spot Patches",
    sku: "GDN-ACN-031",
    category: "Acne care",
    pack: "Sheet · 36 patches",
    rating: 4.3,
    ratingCount: 3260,
    current: { complaints: 7, reviews: 360 },
    baseline: { complaints: 170, reviews: 8200 },
    sentimentDelta: 0,
    competitors: { hasaki: { complaints: 7, reviews: 350 }, watsons: { complaints: 6, reviews: 340 } },
    sources: { app: 2, marketplace: 3, service: 1, social: 1 },
    themes: [{ label: "Low adhesion", count: 5 }, { label: "Packaging bent", count: 2 }],
  },
  {
    id: "P-LP01",
    name: "Ceramide Rescue Lip Balm",
    shortName: "Ceramide Lip Balm",
    sku: "GDN-LIP-011",
    category: "Lip care",
    pack: "Stick · 4.5 g",
    rating: 4.7,
    ratingCount: 2890,
    current: { complaints: 5, reviews: 330 },
    baseline: { complaints: 125, reviews: 6900 },
    sentimentDelta: 4,
    competitors: { hasaki: { complaints: 5, reviews: 320 }, watsons: { complaints: 4, reviews: 310 } },
    sources: { app: 2, marketplace: 1, service: 1, social: 1 },
    themes: [{ label: "Stick mechanism", count: 3 }, { label: "Melting", count: 2 }],
  },
];

export type Evidence = {
  id: string;
  productId: ProductId;
  quote: string;
  source: SourceKey;
  timestamp: string;
  confidence: number;
  stance: "support" | "contradict";
};

const EVIDENCE: Evidence[] = [
  {
    id: "fb-P-UV01-pkg-01",
    productId: "P-UV01",
    quote: "Đặt online nhận hộp ướt nhẹp, đầu pump bị lỏng nên kem chảy gần nửa chai.",
    source: "marketplace",
    timestamp: "2026-07-11T08:42:00+07:00",
    confidence: 0.98,
    stance: "support",
  },
  {
    id: "fb-P-UV02-pkg-01",
    productId: "P-UV02",
    quote: "Mở parcel thấy túi chống sốc ướt, cổ chai rò dù nắp vẫn đóng.",
    source: "app",
    timestamp: "2026-07-11T07:56:00+07:00",
    confidence: 0.96,
    stance: "support",
  },
  {
    id: "fb-P-UV01-pkg-02",
    productId: "P-UV01",
    quote: "Nắp pump bật ra ngay lần đầu mở, sản phẩm lem hết trong túi giao hàng.",
    source: "service",
    timestamp: "2026-07-11T06:30:00+07:00",
    confidence: 0.94,
    stance: "support",
  },
  {
    id: "fb-P-CL01-pkg-01",
    productId: "P-CL01",
    quote: "Tuýp sữa rửa mặt bị nứt ngay mép nắp, hàng dính hết trong hộp.",
    source: "social",
    timestamp: "2026-07-10T22:18:00+07:00",
    confidence: 0.91,
    stance: "support",
  },
  {
    id: "fb-P-MO01-pkg-01",
    productId: "P-MO01",
    quote: "Hũ lăn trong hộp vì không có chèn, seal bung và kem lem vào nắp.",
    source: "marketplace",
    timestamp: "2026-07-10T20:44:00+07:00",
    confidence: 0.89,
    stance: "support",
  },
  {
    id: "fb-P-SE01-pkg-01",
    productId: "P-SE01",
    quote: "Đầu dropper hơi lỏng, có vài giọt trong hộp nhưng chai vẫn gần đầy.",
    source: "social",
    timestamp: "2026-07-10T18:04:00+07:00",
    confidence: 0.78,
    stance: "support",
  },
  {
    id: "fb-P-UV01-contradict-01",
    productId: "P-UV01",
    quote: "Hộp hơi móp nhưng chai không chảy, pump vẫn dùng bình thường.",
    source: "app",
    timestamp: "2026-07-10T16:40:00+07:00",
    confidence: 0.76,
    stance: "contradict",
  },
  {
    id: "fb-P-UV02-contradict-01",
    productId: "P-UV02",
    quote: "Bao bì mỏng hơn kỳ vọng nhưng seal và nắp vẫn còn nguyên.",
    source: "marketplace",
    timestamp: "2026-07-10T15:20:00+07:00",
    confidence: 0.72,
    stance: "contradict",
  },
];

export type Activity = {
  id: string;
  productId: ProductId;
  timestamp: string;
  timeLabel: string;
  source: SourceKey;
  issue: string;
  detail: string;
  delta: string;
};

const ACTIVITIES: Activity[] = [
  {
    id: "act-01",
    productId: "P-UV01",
    timestamp: "2026-07-11T08:42:00+07:00",
    timeLabel: "08:42",
    source: "marketplace",
    issue: "Leakage cluster accelerated",
    detail: "5 new matching reviews in 45 minutes",
    delta: "+5",
  },
  {
    id: "act-02",
    productId: "P-UV02",
    timestamp: "2026-07-11T07:56:00+07:00",
    timeLabel: "07:56",
    source: "app",
    issue: "Loose pump-neck mentions",
    detail: "Topic appeared across app and marketplace",
    delta: "+4",
  },
  {
    id: "act-03",
    productId: "P-UV01",
    timestamp: "2026-07-11T06:30:00+07:00",
    timeLabel: "06:30",
    source: "service",
    issue: "Support tickets linked",
    detail: "3 tickets matched the packaging signal",
    delta: "+3",
  },
  {
    id: "act-04",
    productId: "P-CL01",
    timestamp: "2026-07-10T22:18:00+07:00",
    timeLabel: "22:18",
    source: "social",
    issue: "Cracked-cap mention",
    detail: "Low-volume related packaging issue",
    delta: "+1",
  },
  {
    id: "act-05",
    productId: "P-MO01",
    timestamp: "2026-07-10T20:44:00+07:00",
    timeLabel: "20:44",
    source: "marketplace",
    issue: "Seal failure mention",
    detail: "Evidence suggests insufficient protective wrap",
    delta: "+1",
  },
  {
    id: "act-06",
    productId: "P-SE01",
    timestamp: "2026-07-10T18:04:00+07:00",
    timeLabel: "18:04",
    source: "social",
    issue: "Dropper feedback improving",
    detail: "Current share remains below the 28-day baseline",
    delta: "−2%",
  },
];

type HypothesisFixture = {
  id: string;
  title: string;
  summary: string;
  support: Partial<Record<ProductId, number>>;
  contradict: Partial<Record<ProductId, number>>;
  channels: Partial<Record<ProductId, SourceKey[]>>;
};

const HYPOTHESES: HypothesisFixture[] = [
  {
    id: "H-PUMP",
    title: "Pump-neck seal or cap fit",
    summary: "Two sunscreen pump SKUs show repeated leakage and loose-cap language across online channels.",
    support: { "P-UV01": 84, "P-UV02": 70 },
    contradict: { "P-UV01": 7, "P-UV02": 5 },
    channels: {
      "P-UV01": ["app", "marketplace", "service"],
      "P-UV02": ["app", "marketplace", "social"],
    },
  },
  {
    id: "H-FULFILL",
    title: "Insufficient protective wrapping",
    summary: "Wet boxes and movement inside parcels suggest inconsistent online-fulfilment protection.",
    support: { "P-UV01": 3, "P-UV02": 2, "P-CL01": 2, "P-MO01": 1, "P-SE01": 0 },
    contradict: { "P-UV01": 2, "P-UV02": 1, "P-CL01": 1, "P-MO01": 1, "P-SE01": 1 },
    channels: {
      "P-UV01": ["marketplace", "service"],
      "P-UV02": ["app", "marketplace"],
      "P-CL01": ["social"],
      "P-MO01": ["marketplace"],
      "P-SE01": [],
    },
  },
  {
    id: "H-STORAGE",
    title: "Customer storage after delivery",
    summary: "A minority of mentions may relate to handling after delivery rather than packaging quality.",
    support: { "P-UV01": 1, "P-UV02": 1, "P-CL01": 0, "P-MO01": 0, "P-SE01": 1 },
    contradict: { "P-UV01": 3, "P-UV02": 2, "P-CL01": 1, "P-MO01": 1, "P-SE01": 1 },
    channels: {
      "P-UV01": ["social"],
      "P-UV02": ["social"],
      "P-CL01": [],
      "P-MO01": [],
      "P-SE01": ["social"],
    },
  },
];

const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);
const percent = (part: number, whole: number) => (whole === 0 ? null : (part / whole) * 100);

export type DashboardStatus = "critical" | "watch" | "improving";

export function deriveDashboard(selectedIds: ProductId[]) {
  const selectedProducts = PRODUCTS.filter((product) => selectedIds.includes(product.id));
  const currentComplaints = sum(selectedProducts.map((product) => product.current.complaints));
  const currentReviews = sum(selectedProducts.map((product) => product.current.reviews));
  const baselineComplaints = sum(selectedProducts.map((product) => product.baseline.complaints));
  const baselineReviews = sum(selectedProducts.map((product) => product.baseline.reviews));
  const complaintShare = percent(currentComplaints, currentReviews);
  const baselineShare = percent(baselineComplaints, baselineReviews);
  const velocity = complaintShare !== null && baselineShare ? complaintShare / baselineShare : null;
  const sentimentDelta = currentReviews
    ? selectedProducts.reduce(
        (total, product) => total + product.sentimentDelta * product.current.reviews,
        0,
      ) / currentReviews
    : null;

  let status: DashboardStatus | null = null;
  if (complaintShare !== null && baselineShare !== null) {
    if (complaintShare < baselineShare) status = "improving";
    else if (currentComplaints >= 15 && velocity !== null && velocity >= 2) status = "critical";
    else status = "watch";
  }

  const sourceCounts = (Object.keys(SOURCE_LABELS) as SourceKey[]).map((source) => ({
    source,
    label: SOURCE_LABELS[source],
    count: sum(selectedProducts.map((product) => product.sources[source])),
  }));

  const themeMap = new Map<string, number>();
  selectedProducts.forEach((product) => {
    product.themes.forEach((theme) => {
      themeMap.set(theme.label, (themeMap.get(theme.label) ?? 0) + theme.count);
    });
  });

  const themes = [...themeMap.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  const affectedProducts = [...selectedProducts].sort((a, b) => {
    const complaintDifference = b.current.complaints - a.current.complaints;
    if (complaintDifference !== 0) return complaintDifference;
    const aShare = a.current.complaints / a.current.reviews;
    const bShare = b.current.complaints / b.current.reviews;
    if (bShare !== aShare) return bShare - aShare;
    return PRODUCT_IDS.indexOf(a.id) - PRODUCT_IDS.indexOf(b.id);
  });

  const evidence = EVIDENCE.filter((item) => selectedIds.includes(item.productId)).sort(
    (a, b) =>
      b.confidence - a.confidence ||
      Date.parse(b.timestamp) - Date.parse(a.timestamp) ||
      a.id.localeCompare(b.id),
  );

  const activities = ACTIVITIES.filter((item) => selectedIds.includes(item.productId)).sort(
    (a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp),
  );

  const hypotheses = HYPOTHESES.map((hypothesis) => {
    const support = sum(selectedIds.map((id) => hypothesis.support[id] ?? 0));
    const contradict = sum(selectedIds.map((id) => hypothesis.contradict[id] ?? 0));
    const channelBreadth = new Set(selectedIds.flatMap((id) => hypothesis.channels[id] ?? [])).size;
    const balance = support + contradict ? support / (support + contradict) : 0;
    const coverage = currentComplaints ? support / currentComplaints : 0;
    const breadth = Math.min(channelBreadth / 3, 1);
    const confidence = 0.45 * balance + 0.3 * coverage + 0.25 * breadth;

    return {
      id: hypothesis.id,
      title: hypothesis.title,
      summary: hypothesis.summary,
      support,
      contradict,
      confidence,
      productIds: selectedIds.filter((id) => (hypothesis.support[id] ?? 0) > 0),
    };
  })
    .filter(
      (hypothesis) =>
        currentComplaints >= 3 &&
        hypothesis.support >= 2 &&
        hypothesis.confidence >= 0.45,
    )
    .sort((a, b) => b.confidence - a.confidence);

  const competitors = (['hasaki', 'watsons'] as const).map((retailer) => {
    const complaints = sum(
      selectedProducts.map((product) => product.competitors[retailer].complaints),
    );
    const reviews = sum(selectedProducts.map((product) => product.competitors[retailer].reviews));
    return { retailer, complaints, reviews, share: percent(complaints, reviews) };
  });

  const selectedNames = selectedProducts.map((product) => product.shortName);
  const scopeLabel =
    selectedProducts.length === PRODUCTS.length
      ? "All products"
      : selectedProducts.length === 1
        ? selectedProducts[0].shortName
        : `${selectedProducts.length} products`;

  const headline = !selectedProducts.length
    ? "Select products to build a feedback cohort"
    : status === "improving"
      ? `${scopeLabel} complaints improved below baseline`
      : selectedProducts.length === 1
        ? `${scopeLabel} complaints increased ${velocity?.toFixed(1)}×`
        : `Packaging complaints increased ${velocity?.toFixed(1)}× in 72 hours`;

  return {
    selectedProducts,
    selectedNames,
    scopeLabel,
    headline,
    currentComplaints,
    currentReviews,
    baselineComplaints,
    baselineReviews,
    complaintShare,
    baselineShare,
    velocity,
    sentimentDelta,
    status,
    sourceCounts,
    themes,
    affectedProducts,
    evidence,
    activities,
    hypotheses,
    competitors,
  };
}

export function normalizeProductIds(ids: string[]): ProductId[] {
  const idSet = new Set(ids.filter((id): id is ProductId => PRODUCT_IDS.includes(id as ProductId)));
  return PRODUCT_IDS.filter((id) => idSet.has(id));
}

export function parseProductSelection(search: string): ProductId[] {
  const params = new URLSearchParams(search);
  if (!params.has("products") || params.get("products") === "all") return [...PRODUCT_IDS];
  const raw = params.get("products") ?? "";
  if (!raw) return [];
  return normalizeProductIds(raw.split(","));
}

export function serializeProductSelection(ids: ProductId[]): string {
  const normalized = normalizeProductIds(ids);
  if (normalized.length === PRODUCT_IDS.length) return "all";
  return normalized.join(",");
}

export function formatPercent(value: number | null, digits = 1) {
  return value === null ? "—" : `${value.toFixed(digits)}%`;
}

export function formatVelocity(value: number | null) {
  return value === null ? "—" : `${value.toFixed(1)}×`;
}
