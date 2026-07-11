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
    expect(screen.queryByRole("heading", { name: "Products to watch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recommended actions" })).not.toBeInTheDocument();
    expect(screen.getByText("480")).toBeInTheDocument();
    expect(screen.getAllByText("Damaged Packaging").length).toBeGreaterThan(0);
    expect(screen.queryByText("Demo", { exact: true })).not.toBeInTheDocument();
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

  it("keeps the benchmark visible after product group filtering", async () => {
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
    await user.click(screen.getByRole("button", { name: /Change product group/ }));
    await user.click(screen.getByRole("button", { name: /Chăm sóc da mặt/ }));
    expect(screen.getByRole("heading", { name: "Social experience score" })).toBeInTheDocument();
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
});
