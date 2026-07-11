import { ChakraProvider } from "@chakra-ui/react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WaitForRunOptions } from "../api/client";
import type { ImportPreviewResponse, RunResponse } from "../api/types";
import { system } from "../theme";

const api = vi.hoisted(() => ({
  fetchImportConfig: vi.fn(),
  detectReviewImport: vi.fn(),
  previewReviewImport: vi.fn(),
  commitReviewImport: vi.fn(),
  waitForRun: vi.fn(),
}));

vi.mock("../api/client", () => api);

import { ReviewImportPanel } from "./ReviewImportPanel";

function renderPanel(onImported = vi.fn()) {
  render(<ChakraProvider value={system}><ReviewImportPanel onImported={onImported} /></ChakraProvider>);
  return onImported;
}

const preview: ImportPreviewResponse = {
  profile: "shopee",
  source_name: "shopee",
  filename: "reviews.csv",
  file_sha256: "hash",
  columns: ["review_text"],
  resolved_mapping: { text: "review_text" },
  total_rows: 2,
  valid_rows: 2,
  invalid_rows: 0,
  samples: [
    {
      source_platform: "shopee",
      brand: "guardian",
      occurred_at: "2026-07-11T00:00:00+07:00",
      rating: 5,
      product_name: "Serum A",
      text: "Great",
    },
  ],
  issues: [],
  mapping: {
    reviewer_name: null,
    review_body: "review_text",
    star_rating: null,
    product_url: null,
    product_name: null,
    review_id: null,
    review_date: null,
  },
};

describe("ReviewImportPanel", () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset());
    api.fetchImportConfig.mockResolvedValue({
      enabled: true,
      max_bytes: 1_000_000,
      profiles: ["shopee", "lazada"],
      accepted_extensions: [".csv", ".xlsx"],
      agentic_detection_enabled: true,
      seller_urls: { shopee: "https://seller.shopee.vn/" },
      last_import_at: null,
      last_import_by_profile: {},
    });
    api.detectReviewImport.mockResolvedValue(preview);
    api.commitReviewImport.mockResolvedValue({
      pipeline_run_id: "run-1",
      status: "queued",
      stage: null,
      started_at: null,
      completed_at: null,
      records_seen: 2,
      records_inserted: 0,
      records_skipped: 0,
      records_failed: 0,
      published_at: null,
      error_summary: null,
    });
  });

  it("previews data before importing", async () => {
    const running: RunResponse = {
      pipeline_run_id: "run-1", status: "running", stage: "classify",
      started_at: null, completed_at: null, records_seen: 2, records_inserted: 0,
      records_skipped: 0, records_failed: 0, published_at: null, error_summary: null,
    };
    const completed: RunResponse = {
      ...running, status: "completed", stage: "publish", records_inserted: 2,
    };
    let pollOptions: WaitForRunOptions | undefined;
    let resolveTerminal: ((value: RunResponse) => void) | undefined;
    api.waitForRun.mockImplementation((_runId: string, options: WaitForRunOptions) => {
      pollOptions = options;
      return new Promise<RunResponse>((resolve) => { resolveTerminal = resolve; });
    });
    const onImported = vi.fn();
    const user = userEvent.setup();
    renderPanel(onImported);

    const fileInput = await screen.findByLabelText("CSV review export");
    expect(screen.queryByLabelText("Admin token")).not.toBeInTheDocument();
    const file = new File(["review_text\nGreat"], "reviews.csv", { type: "text/csv" });
    await user.upload(fileInput, file);

    expect(await screen.findByText("Great")).toBeInTheDocument();
    expect(screen.getByText("2 valid rows, 0 issues")).toBeInTheDocument();
    expect(api.commitReviewImport).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Import reviewed data" }));

    await waitFor(() => expect(screen.getAllByText("Finishing...").length).toBeGreaterThan(0));
    expect(api.detectReviewImport).toHaveBeenCalledWith(file, "shopee", expect.any(AbortSignal));
    expect(api.commitReviewImport).toHaveBeenCalledWith(file, "shopee", expect.any(AbortSignal), preview.mapping);
    act(() => pollOptions?.onUpdate?.(running));
    act(() => resolveTerminal?.(completed));
    expect(await screen.findByText("Import complete")).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("shows a concise partial result", async () => {
    api.waitForRun.mockResolvedValue({
      pipeline_run_id: "run-1", status: "partial", stage: "publish",
      started_at: null, completed_at: null, records_seen: 2, records_inserted: 1,
      records_skipped: 0, records_failed: 1, published_at: null,
      error_summary: "One row failed classification.",
    });
    const onImported = vi.fn();
    const user = userEvent.setup();
    renderPanel(onImported);

    await user.upload(await screen.findByLabelText("CSV review export"), new File(["review_text\nGreat"], "reviews.csv", { type: "text/csv" }));
    await screen.findByText("Great");
    await user.click(screen.getByRole("button", { name: "Import reviewed data" }));

    expect(await screen.findByText("Some reviews could not be imported")).toBeInTheDocument();
    expect(screen.getByText("1 imported - 1 failed")).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("locks the file and marketplace inputs while the file is importing", async () => {
    let resolveDetection: ((value: ImportPreviewResponse) => void) | undefined;
    api.detectReviewImport.mockReturnValue(new Promise((resolve) => { resolveDetection = resolve; }));
    api.commitReviewImport.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    renderPanel();

    const fileInput = await screen.findByLabelText("CSV review export");
    const profile = screen.getByLabelText("Shopee");
    await user.upload(fileInput, new File(["review_text\nGreat"], "reviews.csv", { type: "text/csv" }));

    expect(await screen.findByText("Previewing file...")).toBeInTheDocument();
    expect(fileInput).not.toBeDisabled();
    expect(profile).not.toBeDisabled();
    act(() => resolveDetection?.(preview));
    await screen.findByText("Great");
    await user.click(screen.getByRole("button", { name: "Import reviewed data" }));

    await waitFor(() => expect(api.commitReviewImport).toHaveBeenCalled());
    expect(fileInput).toBeDisabled();
    expect(profile).toBeDisabled();
  });
});
