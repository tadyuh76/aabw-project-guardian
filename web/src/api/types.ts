export type DashboardState = "ready" | "partial" | "empty";
export type HealthStatus = "healthy" | "stale" | "partial" | "failed" | "unknown";

export interface DashboardWindows {
  currentStart: string | null;
  currentEnd: string | null;
  baselineStart: string | null;
  baselineEnd: string | null;
  businessTimezone: string | null;
}

export interface DashboardCoverage {
  feedbackItems: number;
  analyzedItems: number;
  relevantItems: number;
  timeEligibleItems: number;
  productAttributedItems: number;
}

export interface ProductPeriodCounts {
  feedback: number;
  complaints: number;
  positive: number;
  neutral: number;
}

export interface ProductTheme {
  label: string;
  subtopic: string | null;
  count: number;
  baselineCount: number;
  percentageChange: number | null;
}

export interface ProductRatingCount {
  rating: number;
  count: number;
}

export interface ProductRatingTrendPoint {
  date: string;
  platform: string;
  averageRating: number;
  count: number;
  predicted: boolean;
}

export interface DashboardProduct {
  id: string;
  name: string | null;
  shortName: string | null;
  sku: string | null;
  category: string | null;
  pack: string | null;
  metadataComplete: boolean;
  rating: number | null;
  ratingCount: number | null;
  totalFeedback: number;
  current: ProductPeriodCounts;
  baseline: ProductPeriodCounts;
  overall?: ProductPeriodCounts;
  sentimentDelta: number | null;
  sources: Array<{ sourceGroup: string; count: number }>;
  themes: ProductTheme[];
  ratingDistribution: ProductRatingCount[];
  baselineRatingDistribution: ProductRatingCount[];
  allRatingDistribution?: ProductRatingCount[];
  ratingTrend: ProductRatingTrendPoint[];
  negativeFeedback: ProductTheme[];
  problems: ProductTheme[];
  allProblems?: ProductTheme[];
}

export interface DashboardEvidence {
  id: string;
  productId: string | null;
  text: string;
  sourceGroup: string;
  sourcePlatform: string;
  sourceUrl: string | null;
  timestamp: string | null;
  confidence: number | null;
  stance: string | null;
  topic: string | null;
  subtopic: string | null;
  sentiment: string | null;
}

export interface DashboardInsight {
  id: string | null;
  title: string;
  summary: string | null;
  topic: string | null;
  label: string | null;
  status: string | null;
  confidenceLevel: string | null;
  confidenceScore: number | null;
  recommendedActions: string[];
  currentShare: number | null;
  baselineShare: number | null;
  percentagePointChange: number | null;
  growthMultiple: number | null;
}

export interface BenchmarkBrand {
  brand: string;
  feedback: number | null;
  complaints: number | null;
  positive: number | null;
  neutral: number | null;
  rating: number | null;
  ratingCount: number | null;
  share: number | null;
}

export interface DashboardBenchmark {
  comparable: boolean;
  reason: string | null;
  brands: BenchmarkBrand[];
}

export interface DashboardData {
  mode: "demo" | "live" | string;
  asOf: string | null;
  lastUpdated: string | null;
  overallHealth: HealthStatus;
  dataState: DashboardState;
  windows: DashboardWindows;
  coverage: DashboardCoverage;
  messages: string[];
  products: DashboardProduct[];
  evidence: DashboardEvidence[];
  primaryInsight: DashboardInsight | null;
  benchmark: DashboardBenchmark | null;
}

export const REVIEW_IMPORT_PROFILES = [
  "guardian_ecommerce",
  "tiktok_shop",
  "shopee",
  "lazada",
  "grabmart",
] as const;

export type ReviewImportProfile = (typeof REVIEW_IMPORT_PROFILES)[number];

export interface ImportConfigResponse {
  enabled: boolean;
  max_bytes: number;
  profiles: ReviewImportProfile[];
  accepted_extensions: string[];
  agentic_detection_enabled: boolean;
  seller_urls: Partial<Record<ReviewImportProfile, string>>;
  last_import_at: string | null;
  last_import_by_profile: Partial<Record<ReviewImportProfile, string | null>>;
}

export interface ImportIssueResponse {
  row_number: number;
  code: string;
  message: string;
  field: string | null;
  masked_sample: Record<string, unknown>;
}

export interface ImportPreviewResponse {
  profile: string;
  source_name: string;
  filename: string;
  file_sha256: string;
  columns: string[];
  resolved_mapping: Record<string, string>;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  samples: Array<Record<string, unknown>>;
  issues: ImportIssueResponse[];
  mapping?: ImportColumnMapping;
  duplicate_file?: boolean;
  sample_rows_sent?: number;
}

export interface ImportColumnMapping {
  reviewer_name: string | null;
  review_body: string;
  star_rating: string | null;
  product_url: string | null;
  product_name: string | null;
  review_id: string | null;
  review_date: string | null;
}

export interface RunResponse {
  pipeline_run_id: string;
  status: "queued" | "running" | "completed" | "partial" | "failed";
  stage: string | null;
  started_at: string | null;
  completed_at: string | null;
  records_seen: number;
  records_inserted: number;
  records_skipped: number;
  records_failed: number;
  published_at: string | null;
  error_summary: string | null;
}
