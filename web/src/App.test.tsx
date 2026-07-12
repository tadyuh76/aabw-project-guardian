import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dashboardFixture } from "./test/dashboardFixture";

const api = vi.hoisted(() => ({
  fetchDashboard: vi.fn(),
  fetchFeedback: vi.fn(),
  fetchImportConfig: vi.fn(),
  previewReviewImport: vi.fn(),
  commitReviewImport: vi.fn(),
  waitForRun: vi.fn(),
}));
const pdf = vi.hoisted(() => ({
  captureDashboardPdf: vi.fn(),
}));

vi.mock("./api/client", () => api);
vi.mock("./utils/dashboardPdf", () => pdf);

import { App } from "./App";

describe("App dashboard states", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    Object.values(api).forEach((mock) => mock.mockReset());
    pdf.captureDashboardPdf.mockReset();
    pdf.captureDashboardPdf.mockResolvedValue(undefined);
    api.fetchImportConfig.mockResolvedValue({
      enabled: false,
      max_bytes: 1000,
      profiles: [],
      accepted_extensions: [".csv"],
      agentic_detection_enabled: false,
      seller_urls: {},
      last_import_at: null,
      last_import_by_profile: {},
    });
  });

  it("renders only values from a successful dashboard response", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture({ mode: "demo" }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("tab", { name: "Dashboard" }));

    expect(await screen.findByText("Packaging complaints declined")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recent review signals" })).not.toBeInTheDocument();
    expect(screen.queryByText("The cleanser arrived securely packed.", { exact: false })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review sentiment" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Review sentiment" })).getAllByRole("listitem").map((item) => item.getAttribute("aria-label"))).toEqual([
      "Positive reviews: 520 (72%)",
      "Negative reviews: 80 (11%)",
    ]);
    expect(screen.queryByRole("heading", { name: "Top 5 negative feedback" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top 5 product problems" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rating trend & forecast" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Social experience score" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Guardian review keyword cloud" })).not.toBeInTheDocument();
    expect(screen.queryByText("cleanser")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Products to watch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recommended actions" })).not.toBeInTheDocument();
    expect(screen.getByText("520")).toBeInTheDocument();
    expect(screen.getAllByText("Damaged Packaging").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Directional all-source comparison/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Net Sentiment Score/)).not.toBeInTheDocument();
    expect(screen.queryByText("Demo", { exact: true })).not.toBeInTheDocument();
  });

  it("exports the selected dashboard view as a PDF capture", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture());
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "30D" }));
    await user.click(await screen.findByRole("button", { name: "Export PDF" }));

    await waitFor(() => expect(pdf.captureDashboardPdf).toHaveBeenCalledTimes(1));
    const [element, options] = pdf.captureDashboardPdf.mock.calls[0]!;
    expect(element).toBeInstanceOf(HTMLElement);
    expect(element).toContainElement(screen.getByRole("heading", { name: "Rating distribution" }));
    expect(options).toEqual({ filename: "guardian-dashboard-30d.pdf" });
  });

  it("keeps partial backend copy out of the dashboard", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture({
      dataState: "partial",
      overallHealth: "partial",
      messages: ["Only marketplace sources completed in this window."],
    }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("tab", { name: "Dashboard" }));

    expect(await screen.findByRole("heading", { name: "Review sentiment" })).toBeInTheDocument();
    expect(screen.queryByText("Only marketplace sources completed in this window.")).not.toBeInTheDocument();
  });

  it("does not render backend notes as visible dashboard copy", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture({
      dataState: "ready",
      messages: ["Some Guardian feedback has no trustworthy occurrence date and is excluded from period metrics."],
    }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("tab", { name: "Dashboard" }));

    expect(await screen.findByRole("heading", { name: "Review sentiment" })).toBeInTheDocument();
    expect(screen.queryByText("Backend data notes")).not.toBeInTheDocument();
    expect(screen.queryByText(/Some Guardian feedback has no trustworthy occurrence date/)).not.toBeInTheDocument();
  });

  it("opens dashboard all-time without a product group filter", async () => {
    const fixture = dashboardFixture();
    const first = fixture.products[0]!;
    api.fetchDashboard.mockResolvedValue({
      ...fixture,
      products: [first, {
        ...first,
        id: "second-product",
        name: "Second Product",
        shortName: "Second Product",
        category: "Makeup",
      }],
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("tab", { name: "Dashboard" }));

    expect(await screen.findByRole("heading", { name: "Social experience score" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Change product group/ })).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Review sentiment" })).getAllByRole("listitem").map((item) => item.getAttribute("aria-label"))).toEqual([
      "Positive reviews: 1,040 (72%)",
      "Negative reviews: 160 (11%)",
    ]);
  });

  it("shows an honest empty state without product fixtures", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture({
      dataState: "empty",
      products: [],
      evidence: [],
      primaryInsight: null,
      benchmark: null,
      messages: ["No time-eligible product feedback was found."],
    }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("tab", { name: "Dashboard" }));

    expect(await screen.findByRole("heading", { name: "No product-attributed feedback is available" })).toBeInTheDocument();
    expect(screen.getByText("No time-eligible product feedback was found.")).toBeInTheDocument();
    expect(screen.queryByText("CeraVe Foaming Cleanser")).not.toBeInTheDocument();
  });

  it("shows an API error and retries without a demo fallback", async () => {
    api.fetchDashboard
      .mockRejectedValueOnce(new Error("connection refused"))
      .mockResolvedValueOnce(dashboardFixture());
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("tab", { name: "Dashboard" }));

    expect(await screen.findByText("Dashboard data could not be loaded")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry dashboard" }));
    expect(await screen.findByRole("heading", { name: "Review sentiment" })).toBeInTheDocument();
    expect(api.fetchDashboard).toHaveBeenCalledTimes(2);
  });

  it("opens the dashboard at the root route and moves import to /import", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture());
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Review sentiment" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Import reviews" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Import" }));
    expect(window.location.pathname).toBe("/import");
    expect(await screen.findByText("Review imports are disabled.")).toBeInTheDocument();
  });

  it("opens import directly from /import without loading dashboard data", async () => {
    window.history.replaceState(null, "", "/import");
    api.fetchDashboard.mockResolvedValue(dashboardFixture());

    render(<App />);

    expect(await screen.findByText("Review imports are disabled.")).toBeInTheDocument();
    expect(api.fetchDashboard).not.toHaveBeenCalled();
  });

  it("opens reviews at /reviews with platform, time-frame, sort, search, and source links", async () => {
    window.history.replaceState(null, "", "/reviews");
    api.fetchDashboard.mockResolvedValue(dashboardFixture());
    api.fetchFeedback.mockResolvedValue({
      mode: "live",
      syntheticItems: 0,
      total: 3,
      limit: 200,
      offset: 0,
      items: [
        {
          feedbackId: "feedback-1",
          productName: "CeraVe Foaming Cleanser",
          productCategory: null,
          text: "The cleanser arrived securely packed.",
          sourceGroup: "marketplace",
          sourcePlatform: "Shopee",
          sourceUrl: "https://shopee.vn/product/cerave-473",
          occurredAt: "2026-07-10T10:00:00Z",
          observedAt: "2026-07-10T10:00:00Z",
          occurredAtQuality: "exact",
          confidence: 0.91,
          topic: "packaging",
          subtopic: "seal",
          sentiment: "positive",
          brand: "guardian",
          intent: null,
          rating: null,
          store: null,
          insightIds: [],
          isSynthetic: false,
        },
        {
          feedbackId: "feedback-2",
          productName: "CeraVe Foaming Cleanser",
          productCategory: null,
          text: "Watsons delivery was late.",
          sourceGroup: "marketplace",
          sourcePlatform: "Watsons",
          sourceUrl: "https://www.watsons.vn/product/cerave-473",
          occurredAt: "2026-06-10T10:00:00Z",
          observedAt: "2026-06-10T10:00:00Z",
          occurredAtQuality: "exact",
          confidence: 0.83,
          topic: "delivery",
          subtopic: null,
          sentiment: "negative",
          brand: "watsons",
          intent: null,
          rating: null,
          store: null,
          insightIds: [],
          isSynthetic: false,
        },
        {
          feedbackId: "feedback-3",
          productName: null,
          productCategory: null,
          text: "Facebook post mentioned skin irritation.",
          sourceGroup: "social",
          sourcePlatform: "Facebook",
          sourceUrl: "https://www.facebook.com/example-review",
          occurredAt: null,
          observedAt: "2026-07-10T10:00:00Z",
          occurredAtQuality: "missing",
          confidence: 0.74,
          topic: "skin irritation",
          subtopic: null,
          sentiment: "negative",
          brand: "guardian",
          intent: null,
          rating: null,
          store: null,
          insightIds: [],
          isSynthetic: false,
        },
      ],
    });
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Reviews" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter reviews by platform" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter reviews by time frame" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Sort reviews" })).toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "Problem" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "URL" })).not.toBeInTheDocument();
    expect(screen.getByText("Seal quality")).toBeInTheDocument();
    expect(screen.queryByText("91% confidence")).not.toBeInTheDocument();
    expect(screen.queryByText("Packaging")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /The cleanser arrived securely packed/i })).toHaveAttribute("href", "https://shopee.vn/product/cerave-473");
    expect(screen.getAllByRole("link", { name: /CeraVe Foaming Cleanser/i }).some((link) => link.getAttribute("href") === "https://shopee.vn/product/cerave-473")).toBe(true);

    await user.click(screen.getByRole("combobox", { name: "Filter reviews by platform" }));
    await user.click(await screen.findByRole("option", { name: "Watsons" }));
    expect(screen.getByText("Watsons delivery was late.")).toBeInTheDocument();
    expect(screen.getByText("Late delivery")).toBeInTheDocument();
    expect(screen.queryByText("The cleanser arrived securely packed.")).not.toBeInTheDocument();

    await user.clear(screen.getByRole("textbox", { name: "Search reviews" }));
    await user.type(screen.getByRole("textbox", { name: "Search reviews" }), "delivery");
    expect(screen.getByRole("link", { name: /Watsons delivery was late/i })).toHaveAttribute("href", "https://www.watsons.vn/product/cerave-473");

    await user.clear(screen.getByRole("textbox", { name: "Search reviews" }));
    await user.click(screen.getByRole("combobox", { name: "Filter reviews by platform" }));
    await user.click(await screen.findByRole("option", { name: "Facebook" }));
    expect(screen.getByText("Null")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("Skin irritation")).toBeInTheDocument();
    expect(screen.queryByText("Social")).not.toBeInTheDocument();
  });
});
