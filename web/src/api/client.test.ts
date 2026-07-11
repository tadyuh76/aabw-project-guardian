import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchDashboard, normalizeDashboard, waitForRun } from "./client";

const wirePayload = {
  mode: "live",
  as_of: "2026-07-11T09:00:00Z",
  last_updated: "2026-07-11T09:05:00Z",
  overall_health: "healthy",
  data_state: "ready",
  windows: {
    current_start: "2026-07-04T00:00:00Z",
    current_end: "2026-07-11T00:00:00Z",
    baseline_start: "2026-06-27T00:00:00Z",
    baseline_end: "2026-07-04T00:00:00Z",
    business_timezone: "Asia/Ho_Chi_Minh",
  },
  coverage: {
    feedback_items: 40,
    analyzed_items: 38,
    relevant_items: 30,
    time_eligible_items: 28,
    product_attributed_items: 22,
  },
  messages: [],
  products: [{
    id: "product-1",
    name: "Real Product",
    short_name: "Real Product",
    category: null,
    sku: null,
    pack: null,
    metadata_complete: false,
    rating: null,
    rating_count: 0,
    total_feedback: 22,
    current: { feedback: 12, complaints: 3, positive: 4, neutral: 5 },
    baseline: { feedback: 10, complaints: 2, positive: 4, neutral: 4 },
    sentiment_delta: null,
    sources: { marketplace: 12 },
    themes: [{ label: "Delivery", count: 3 }],
  }],
  evidence: [{
    id: "evidence-1",
    product_id: "product-1",
    text: "A redacted customer report",
    source_group: "marketplace",
    source_platform: "Shopee",
    source_url: null,
    timestamp: null,
    confidence: 0.8,
    stance: "support",
    topic: "delivery",
    subtopic: "late",
    sentiment: "negative",
  }],
  primary_insight: {
    insight_id: "insight-1",
    title: "Delivery mentions increased",
    what_changed: "Three current complaints were classified.",
    label: "watch",
    status: "open",
    topic: "delivery",
    recommended_actions: ["Review delivery evidence."],
    confidence: { level: "medium", score: 0.72 },
    metrics: { current_share: 0.25, baseline_share: 0.2, percentage_point_change: 5, growth_multiple: 1.25 },
  },
  benchmark: {
    comparable: true,
    reason: null,
    aggregates: [
      { brand: "guardian", feedback: 12, complaints: 3, positive: 4, neutral: 5, rating: null, rating_count: 0 },
      { brand: "hasaki", feedback: 20, complaints: 2, positive: 12, neutral: 6, rating: 4.4, rating_count: 20 },
      { brand: "watsons", feedback: 18, complaints: 3, positive: 9, neutral: 6, rating: 4.1, rating_count: 18 },
    ],
  },
};

afterEach(() => vi.unstubAllGlobals());

describe("dashboard API contract", () => {
  it("requests the same-origin endpoint and normalizes the backend payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(wirePayload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchDashboard();

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/dashboard", expect.objectContaining({
      headers: { Accept: "application/json" },
    }));
    expect(result.products[0]).toMatchObject({
      id: "product-1",
      metadataComplete: false,
      sources: [{ sourceGroup: "marketplace", count: 12 }],
      themes: [{ label: "Delivery", count: 3 }],
    });
    expect(result.primaryInsight?.title).toBe("Delivery mentions increased");
    expect(result.primaryInsight).toMatchObject({ label: "watch", status: "open" });
    expect(result.benchmark?.brands.map((brand) => brand.brand)).toEqual(["guardian", "hasaki", "watsons"]);
    expect(result.benchmark?.brands[0]?.share).toBe(0.25);
    expect(result.evidence[0]?.sourceUrl).toBeNull();
  });

  it("rejects an invalid truth state instead of inventing a fallback", () => {
    expect(() => normalizeDashboard({ ...wirePayload, data_state: "unknown" })).toThrow("invalid data state");
  });

  it("polls a run until it reaches a terminal state", async () => {
    const running = {
      pipeline_run_id: "run/1", status: "running", stage: "classify",
      started_at: null, completed_at: null, records_seen: 2, records_inserted: 0,
      records_skipped: 0, records_failed: 0, published_at: null, error_summary: null,
    };
    const completed = { ...running, status: "completed", stage: "publish", records_inserted: 2 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(running), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(completed), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const updates: string[] = [];

    const result = await waitForRun("run/1", {
      intervalMs: 0,
      timeoutMs: 1_000,
      onUpdate: (run) => updates.push(run.status),
    });

    expect(result.status).toBe("completed");
    expect(updates).toEqual(["running", "completed"]);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/runs/run%2F1", expect.any(Object));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not start polling when already aborted", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    controller.abort();

    await expect(waitForRun("run-1", { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
