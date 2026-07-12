import {
  REVIEW_IMPORT_PROFILES,
  type BenchmarkBrand,
  type DashboardBenchmark,
  type DashboardCoverage,
  type DashboardData,
  type DashboardEvidence,
  type DashboardInsight,
  type DashboardProduct,
  type DashboardState,
  type DashboardWordCloudTerm,
  type DashboardWindows,
  type HealthStatus,
  type ImportConfigResponse,
  type ImportColumnMapping,
  type ImportPreviewResponse,
  type ProductPeriodCounts,
  type ReviewImportProfile,
  type RunResponse,
} from "./types";

const configuredBase = String(import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const REQUEST_TIMEOUT_MS = 10_000;
const IMPORT_REQUEST_TIMEOUT_MS = 60_000;
const RUN_POLL_INTERVAL_MS = 1_500;
const RUN_POLL_TIMEOUT_MS = 10 * 60_000;

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

function apiUrl(path: string): string {
  return `${configuredBase}${path}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function countValue(value: unknown): number {
  return Math.max(0, numberValue(value) ?? 0);
}

function booleanValue(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

function getRecord(record: Record<string, unknown>, key: string): Record<string, unknown> {
  return isRecord(record[key]) ? record[key] : {};
}

function periodCounts(value: unknown): ProductPeriodCounts {
  const record = isRecord(value) ? value : {};
  return {
    feedback: countValue(record.feedback ?? record.reviews),
    complaints: countValue(record.complaints),
    positive: countValue(record.positive),
    neutral: countValue(record.neutral),
  };
}

function normalizeSources(value: unknown): DashboardProduct["sources"] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (!isRecord(item)) return [];
      const sourceGroup = stringValue(item.source_group ?? item.sourceGroup);
      return sourceGroup ? [{ sourceGroup, count: countValue(item.count) }] : [];
    });
  }
  if (!isRecord(value)) return [];
  return Object.entries(value).flatMap(([sourceGroup, count]) =>
    numberValue(count) === null ? [] : [{ sourceGroup, count: countValue(count) }],
  );
}

function normalizeThemes(value: unknown): DashboardProduct["themes"] {
  return Array.isArray(value)
    ? value.flatMap((item) => {
        if (!isRecord(item)) return [];
        const label = stringValue(item.label ?? item.topic);
        if (!label) return [];
        return [{
          label,
          subtopic: stringValue(item.subtopic),
          count: countValue(item.count),
          baselineCount: countValue(item.baseline_count ?? item.baselineCount),
          percentageChange: numberValue(item.percentage_change ?? item.percentageChange),
        }];
      })
    : [];
}

function normalizeRatingDistribution(value: unknown): DashboardProduct["ratingDistribution"] {
  return Array.isArray(value)
    ? value.flatMap((item) => {
        if (!isRecord(item)) return [];
        const rating = numberValue(item.rating);
        return rating !== null && rating >= 1 && rating <= 5
          ? [{ rating, count: countValue(item.count) }]
          : [];
      })
    : [];
}

function normalizeRatingTrend(value: unknown): DashboardProduct["ratingTrend"] {
  return Array.isArray(value) ? value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const date = stringValue(item.date);
    const platform = stringValue(item.platform);
    const averageRating = numberValue(item.average_rating ?? item.averageRating);
    if (!date || !platform || averageRating === null) return [];
    return [{ date, platform, averageRating, count: countValue(item.count), predicted: booleanValue(item.predicted) }];
  }) : [];
}

function normalizeProduct(value: unknown): DashboardProduct | null {
  if (!isRecord(value)) return null;
  const id = stringValue(value.id);
  if (!id) return null;
  const themes = normalizeThemes(value.themes);
  return {
    id,
    name: stringValue(value.name),
    shortName: stringValue(value.short_name ?? value.shortName),
    sku: stringValue(value.sku),
    category: stringValue(value.category),
    pack: stringValue(value.pack),
    metadataComplete: booleanValue(value.metadata_complete ?? value.metadataComplete),
    rating: numberValue(value.rating),
    ratingCount: numberValue(value.rating_count ?? value.ratingCount),
    totalFeedback: countValue(value.total_feedback ?? value.totalFeedback),
    current: periodCounts(value.current),
    baseline: periodCounts(value.baseline),
    overall: periodCounts(value.overall),
    sentimentDelta: numberValue(value.sentiment_delta ?? value.sentimentDelta),
    sources: normalizeSources(value.sources),
    themes,
    ratingDistribution: normalizeRatingDistribution(value.rating_distribution ?? value.ratingDistribution),
    baselineRatingDistribution: normalizeRatingDistribution(value.baseline_rating_distribution ?? value.baselineRatingDistribution),
    allRatingDistribution: normalizeRatingDistribution(value.all_rating_distribution ?? value.allRatingDistribution),
    ratingTrend: normalizeRatingTrend(value.rating_trend ?? value.ratingTrend),
    negativeFeedback: normalizeThemes(value.negative_feedback ?? value.negativeFeedback),
    problems: normalizeThemes(value.problems ?? value.themes),
    allNegativeFeedback: normalizeThemes(value.all_negative_feedback ?? value.allNegativeFeedback),
    allProblems: normalizeThemes(value.all_problems ?? value.allProblems),
  };
}

function normalizeEvidence(value: unknown): DashboardEvidence | null {
  if (!isRecord(value)) return null;
  const id = stringValue(value.id);
  const text = stringValue(value.text ?? value.text_redacted);
  if (!id || !text) return null;
  return {
    id,
    productId: stringValue(value.product_id ?? value.productId),
    text,
    sourceGroup: stringValue(value.source_group ?? value.sourceGroup) ?? "Unknown source group",
    sourcePlatform: stringValue(value.source_platform ?? value.sourcePlatform) ?? "Unknown source",
    sourceUrl: stringValue(value.source_url ?? value.sourceUrl),
    timestamp: stringValue(value.timestamp ?? value.occurred_at),
    confidence: numberValue(value.confidence),
    stance: stringValue(value.stance ?? value.evidence_role),
    topic: stringValue(value.topic),
    subtopic: stringValue(value.subtopic),
    sentiment: stringValue(value.sentiment),
  };
}

function normalizeInsight(value: unknown): DashboardInsight | null {
  if (!isRecord(value)) return null;
  const title = stringValue(value.title);
  if (!title) return null;
  const confidence = getRecord(value, "confidence");
  const metrics = getRecord(value, "metrics");
  return {
    id: stringValue(value.id ?? value.insight_id),
    title,
    summary: stringValue(value.summary ?? value.what_changed),
    topic: stringValue(value.topic),
    label: stringValue(value.label),
    status: stringValue(value.status),
    confidenceLevel: stringValue(confidence.level ?? value.confidence_level),
    confidenceScore: numberValue(confidence.score ?? value.confidence_score),
    recommendedActions: stringList(value.recommended_actions ?? value.recommendedActions),
    currentShare: numberValue(metrics.current_share ?? value.current_share),
    baselineShare: numberValue(metrics.baseline_share ?? value.baseline_share),
    percentagePointChange: numberValue(
      metrics.percentage_point_change ?? value.percentage_point_change,
    ),
    growthMultiple: numberValue(metrics.growth_multiple ?? value.growth_multiple),
  };
}

function normalizeBenchmarkBrand(value: unknown): BenchmarkBrand | null {
  if (!isRecord(value)) return null;
  const brand = stringValue(value.brand);
  if (!brand) return null;
  const feedback = numberValue(value.feedback ?? value.denominator);
  const complaints = numberValue(value.complaints ?? value.numerator);
  const explicitShare = numberValue(value.share ?? value.weighted_share);
  return {
    brand,
    feedback,
    complaints,
    positive: numberValue(value.positive),
    neutral: numberValue(value.neutral),
    rating: numberValue(value.rating),
    ratingCount: numberValue(value.rating_count ?? value.ratingCount),
    share: explicitShare ?? (
      feedback !== null && feedback > 0 && complaints !== null
        ? complaints / feedback
        : null
    ),
  };
}

function normalizeBenchmark(value: unknown): DashboardBenchmark | null {
  if (!isRecord(value)) return null;
  const rawBrands = value.aggregates ?? value.brands;
  const brands = Array.isArray(rawBrands)
    ? rawBrands.flatMap((item) => {
        const brand = normalizeBenchmarkBrand(item);
        return brand ? [brand] : [];
      })
    : [];
  return {
    comparable: booleanValue(value.comparable),
    reason: stringValue(value.reason ?? value.insufficiency_reason ?? value.note),
    brands,
  };
}

function normalizeWordCloud(value: unknown): DashboardWordCloudTerm[] {
  return Array.isArray(value)
    ? value.flatMap((item) => {
        if (!isRecord(item)) return [];
        const keyword = stringValue(item.keyword ?? item.label);
        if (!keyword) return [];
        return [{ keyword, count: countValue(item.count) }];
      })
    : [];
}

function normalizeWindows(record: Record<string, unknown>): DashboardWindows {
  const windows = getRecord(record, "windows");
  const current = getRecord(record, "window");
  const baseline = getRecord(record, "baseline");
  return {
    currentStart: stringValue(windows.current_start ?? current.start),
    currentEnd: stringValue(windows.current_end ?? current.end),
    baselineStart: stringValue(windows.baseline_start ?? baseline.start),
    baselineEnd: stringValue(windows.baseline_end ?? baseline.end),
    businessTimezone: stringValue(windows.business_timezone),
  };
}

function normalizeCoverage(record: Record<string, unknown>): DashboardCoverage {
  const coverage = getRecord(record, "coverage");
  return {
    feedbackItems: countValue(coverage.feedback_items ?? coverage.total),
    analyzedItems: countValue(coverage.analyzed_items ?? coverage.analyzed),
    relevantItems: countValue(coverage.relevant_items ?? coverage.relevant),
    timeEligibleItems: countValue(coverage.time_eligible_items ?? coverage.time_eligible),
    productAttributedItems: countValue(
      coverage.product_attributed_items ?? coverage.product_attributed,
    ),
  };
}

export function normalizeDashboard(payload: unknown): DashboardData {
  if (!isRecord(payload)) throw new ApiError("Dashboard response is not an object");
  const rawState = stringValue(payload.data_state);
  if (rawState !== "ready" && rawState !== "partial" && rawState !== "empty") {
    throw new ApiError("Dashboard response has an invalid data state");
  }
  const dataState: DashboardState = rawState;
  const rawHealth = stringValue(payload.overall_health ?? payload.health);
  const overallHealth: HealthStatus = (
    rawHealth === "healthy" || rawHealth === "stale" || rawHealth === "partial" || rawHealth === "failed"
  ) ? rawHealth : "unknown";
  if (!Array.isArray(payload.products) || !Array.isArray(payload.evidence)) {
    throw new ApiError("Dashboard response is missing product or evidence arrays");
  }
  return {
    mode: stringValue(payload.mode) ?? "live",
    asOf: stringValue(payload.as_of),
    lastUpdated: stringValue(payload.last_updated),
    overallHealth,
    dataState,
    windows: normalizeWindows(payload),
    coverage: normalizeCoverage(payload),
    messages: stringList(payload.messages),
    products: payload.products.flatMap((item) => {
      const product = normalizeProduct(item);
      return product ? [product] : [];
    }),
    evidence: payload.evidence.flatMap((item) => {
      const evidence = normalizeEvidence(item);
      return evidence ? [evidence] : [];
    }),
    wordCloud: normalizeWordCloud(payload.word_cloud ?? payload.wordCloud),
    primaryInsight: normalizeInsight(payload.primary_insight),
    benchmark: normalizeBenchmark(payload.benchmark ?? payload.competitors),
  };
}

async function responseError(response: Response, fallback: string): Promise<ApiError> {
  let message = fallback;
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload)) {
      const detail = stringValue(payload.detail);
      if (detail) message = detail;
    }
  } catch {
    // A reverse proxy may return an HTML error. The status-bearing fallback remains useful.
  }
  return new ApiError(message, response.status);
}

async function requestJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timeout = globalThis.setTimeout(abort, REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(apiUrl(path), {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw await responseError(response, `Request failed (${response.status})`);
    }
    return await response.json() as T;
  } catch (error) {
    if (controller.signal.aborted && !signal?.aborted) throw new ApiError("Request timed out");
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}

async function requestImport<T>(
  path: string,
  file: File,
  profile: ReviewImportProfile,
  signal?: AbortSignal,
  mapping?: ImportColumnMapping,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timeout = globalThis.setTimeout(abort, IMPORT_REQUEST_TIMEOUT_MS);
  const form = new FormData();
  form.set("file", file, file.name);
  form.set("profile", profile);
  form.set("vietnamese_only", "true");
  if (mapping) form.set("mapping", JSON.stringify(mapping));
  try {
    const response = await fetch(apiUrl(path), {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw await responseError(response, `Import request failed (${response.status})`);
    }
    return await response.json() as T;
  } catch (error) {
    if (controller.signal.aborted && !signal?.aborted) throw new ApiError("Import request timed out");
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}

export async function fetchDashboard(signal?: AbortSignal): Promise<DashboardData> {
  return normalizeDashboard(await requestJson<unknown>("/api/v1/dashboard", signal));
}

export async function fetchImportConfig(signal?: AbortSignal): Promise<ImportConfigResponse> {
  const payload = await requestJson<unknown>("/api/v1/imports/config", signal);
  if (!isRecord(payload)) throw new ApiError("Import configuration is invalid");
  const profiles = Array.isArray(payload.profiles)
    ? payload.profiles.filter((item): item is ReviewImportProfile =>
        typeof item === "string" && REVIEW_IMPORT_PROFILES.includes(item as ReviewImportProfile),
      )
    : [];
  const lastImportByProfile: Partial<Record<ReviewImportProfile, string | null>> = {};
  if (isRecord(payload.last_import_by_profile)) {
    for (const profile of REVIEW_IMPORT_PROFILES) {
      lastImportByProfile[profile] = stringValue(payload.last_import_by_profile[profile]);
    }
  }
  return {
    enabled: booleanValue(payload.enabled),
    max_bytes: countValue(payload.max_bytes),
    profiles,
    accepted_extensions: stringList(payload.accepted_extensions),
    agentic_detection_enabled: booleanValue(payload.agentic_detection_enabled),
    seller_urls: isRecord(payload.seller_urls) ? payload.seller_urls as ImportConfigResponse["seller_urls"] : {},
    last_import_at: stringValue(payload.last_import_at),
    last_import_by_profile: lastImportByProfile,
  };
}

export function previewReviewImport(
  file: File,
  profile: ReviewImportProfile,
  signal?: AbortSignal,
): Promise<ImportPreviewResponse> {
  return requestImport("/api/v1/imports/preview", file, profile, signal);
}

export function detectReviewImport(
  file: File,
  profile: ReviewImportProfile,
  signal?: AbortSignal,
): Promise<ImportPreviewResponse> {
  return requestImport("/api/v1/imports/detect", file, profile, signal);
}

export function commitReviewImport(
  file: File,
  profile: ReviewImportProfile,
  signal?: AbortSignal,
  mapping?: ImportColumnMapping,
): Promise<RunResponse> {
  return requestImport("/api/v1/imports", file, profile, signal, mapping);
}

export function fetchRun(runId: string, signal?: AbortSignal): Promise<RunResponse> {
  return requestJson<RunResponse>(`/api/v1/runs/${encodeURIComponent(runId)}`, signal);
}

export interface WaitForRunOptions {
  signal?: AbortSignal;
  intervalMs?: number;
  timeoutMs?: number;
  onUpdate?: (run: RunResponse) => void;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("Import status polling was aborted", "AbortError");
}

function waitForDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    const timeout = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    const abort = () => {
      globalThis.clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Import status polling was aborted", "AbortError"));
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

export async function waitForRun(
  runId: string,
  options: WaitForRunOptions = {},
): Promise<RunResponse> {
  const intervalMs = Math.max(0, options.intervalMs ?? RUN_POLL_INTERVAL_MS);
  const timeoutMs = Math.max(1, options.timeoutMs ?? RUN_POLL_TIMEOUT_MS);
  const startedAt = Date.now();

  while (true) {
    throwIfAborted(options.signal);
    const run = await fetchRun(runId, options.signal);
    options.onUpdate?.(run);
    if (run.status === "completed" || run.status === "partial" || run.status === "failed") {
      return run;
    }
    if (run.status !== "queued" && run.status !== "running") {
      throw new ApiError(`Import run returned an unsupported status: ${String(run.status)}`);
    }
    const remainingMs = timeoutMs - (Date.now() - startedAt);
    if (remainingMs <= 0) {
      throw new ApiError("Import status polling timed out; the backend run may still be processing.");
    }
    await waitForDelay(Math.min(intervalMs, remainingMs), options.signal);
  }
}
