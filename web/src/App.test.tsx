import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dashboardFixture } from "./test/dashboardFixture";

const api = vi.hoisted(() => ({
  fetchDashboard: vi.fn(),
  fetchImportConfig: vi.fn(),
  previewReviewImport: vi.fn(),
  commitReviewImport: vi.fn(),
  waitForRun: vi.fn(),
}));

vi.mock("./api/client", () => api);

import { App } from "./App";

describe("App dashboard states", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    Object.values(api).forEach((mock) => mock.mockReset());
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
    expect(screen.getByRole("heading", { name: "Rating distribution" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Top 5 negative feedback" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top 5 product problems" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rating trend & forecast" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Social experience score" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Guardian review keyword cloud" })).toBeInTheDocument();
    expect(screen.getByText("cleanser")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Products to watch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recommended actions" })).not.toBeInTheDocument();
    expect(screen.getByText("480")).toBeInTheDocument();
    expect(screen.getAllByText("Damaged Packaging").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Directional all-source comparison/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Net Sentiment Score/)).not.toBeInTheDocument();
    expect(screen.queryByText("Demo", { exact: true })).not.toBeInTheDocument();
  });

  it("exports the full dashboard payload as a PDF report", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture());
    const write = vi.fn();
    const print = vi.fn();
    vi.spyOn(window, "open").mockReturnValue({
      document: { open: vi.fn(), write, close: vi.fn() },
      focus: vi.fn(),
      print,
    } as unknown as Window);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Export PDF" }));

    expect(window.open).toHaveBeenCalledWith("", "_blank");
    expect(print).toHaveBeenCalled();
    const html = String(write.mock.calls[0]?.[0] ?? "");
    expect(html).toContain("Guardian VOC Dashboard");
    expect(html).toContain("CeraVe Foaming Cleanser");
    expect(html).toContain("The cleanser arrived securely packed.");
    expect(html).toContain("Product attributed items");
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

    expect(await screen.findByRole("heading", { name: "Rating distribution" })).toBeInTheDocument();
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

    expect(await screen.findByRole("heading", { name: "Rating distribution" })).toBeInTheDocument();
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
    expect(screen.getByText("960")).toBeInTheDocument();
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
    expect(await screen.findByRole("heading", { name: "Rating distribution" })).toBeInTheDocument();
    expect(api.fetchDashboard).toHaveBeenCalledTimes(2);
  });

  it("opens the dashboard at the root route and moves import to /import", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture());
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Rating distribution" })).toBeInTheDocument();
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
    api.fetchDashboard.mockResolvedValue(dashboardFixture({
      evidence: [
        {
          id: "feedback-1",
          productId: "cerave-473",
          text: "The cleanser arrived securely packed.",
          sourceGroup: "marketplace",
          sourcePlatform: "Shopee",
          sourceUrl: "https://shopee.vn/product/cerave-473",
          timestamp: "2026-07-10T10:00:00Z",
          confidence: 0.91,
          stance: "support",
          topic: "packaging",
          subtopic: "seal",
          sentiment: "positive",
        },
        {
          id: "feedback-2",
          productId: "cerave-473",
          text: "Watsons delivery was late.",
          sourceGroup: "marketplace",
          sourcePlatform: "Watsons",
          sourceUrl: "https://www.watsons.vn/product/cerave-473",
          timestamp: "2026-06-10T10:00:00Z",
          confidence: 0.83,
          stance: "support",
          topic: "delivery",
          subtopic: null,
          sentiment: "negative",
        },
        {
          id: "feedback-3",
          productId: "cerave-473",
          text: "Facebook post mentioned skin irritation.",
          sourceGroup: "social",
          sourcePlatform: "Facebook",
          sourceUrl: "https://www.facebook.com/example-review",
          timestamp: null,
          confidence: 0.74,
          stance: "support",
          topic: "skin irritation",
          subtopic: null,
          sentiment: "negative",
        },
      ],
    }));
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Reviews" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter reviews by platform" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter reviews by time frame" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Sort reviews" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Problem" })).toBeInTheDocument();
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
