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
    api.fetchImportConfig.mockResolvedValue({ enabled: false, max_bytes: 1000, profiles: [], accepted_extensions: [".csv"] });
  });

  it("renders only values from a successful dashboard response", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture());
    render(<App />);

    expect(await screen.findByText("CeraVe Foaming Cleanser")).toBeInTheDocument();
    expect(screen.getByText(/05 Jul 2026 — 11 Jul 2026/)).toBeInTheDocument();
    expect(screen.getByText("Packaging complaints declined")).toBeInTheDocument();
    expect(screen.getByText("Improving decision")).toBeInTheDocument();
    expect(screen.getByText("Workflow: Monitoring")).toBeInTheDocument();
    expect(screen.getByText("The cleanser arrived securely packed.", { exact: false })).toBeInTheDocument();
  });

  it("shows the backend partial message with the usable data", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture({
      dataState: "partial",
      overallHealth: "partial",
      messages: ["Only marketplace sources completed in this window."],
    }));
    render(<App />);

    expect(await screen.findByText("Partial dashboard")).toBeInTheDocument();
    expect(screen.getByText("Only marketplace sources completed in this window.")).toBeInTheDocument();
    expect(screen.getByText("CeraVe Foaming Cleanser")).toBeInTheDocument();
  });

  it("shows non-blocking exclusions as notes without a partial banner", async () => {
    api.fetchDashboard.mockResolvedValue(dashboardFixture({
      dataState: "ready",
      messages: ["Some Guardian feedback has no trustworthy occurrence date and is excluded from period metrics."],
    }));
    render(<App />);

    expect(await screen.findByText("Backend data notes")).toBeInTheDocument();
    expect(screen.getByText(/Some Guardian feedback has no trustworthy occurrence date/)).toBeInTheDocument();
    expect(screen.queryByText("Partial dashboard")).not.toBeInTheDocument();
    expect(screen.getByText("CeraVe Foaming Cleanser")).toBeInTheDocument();
  });

  it("keeps the peer benchmark explicitly portfolio-wide after product filtering", async () => {
    const fixture = dashboardFixture();
    const first = fixture.products[0]!;
    api.fetchDashboard.mockResolvedValue({
      ...fixture,
      products: [first, {
        ...first,
        id: "second-product",
        name: "Second Product",
        shortName: "Second Product",
      }],
    });
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("Global comparable benchmark")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Change product scope/ }));
    await user.click(screen.getByRole("checkbox", { name: /Second Product/ }));
    expect(screen.getByText(/current product selection is narrower/)).toBeInTheDocument();
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
    render(<App />);

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

    expect(await screen.findByText("Dashboard data could not be loaded")).toBeInTheDocument();
    expect(screen.getByText("No cached fixture or fabricated fallback is being shown.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry dashboard" }));
    expect(await screen.findByText("CeraVe Foaming Cleanser")).toBeInTheDocument();
    expect(api.fetchDashboard).toHaveBeenCalledTimes(2);
  });
});
