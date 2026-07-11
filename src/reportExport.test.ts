import { describe, expect, it, vi } from "vitest";
import { deriveDashboard, PRODUCT_IDS } from "./data/dashboard";
import { buildExecutiveReportHtml, openExecutiveReport } from "./reportExport";

const generatedAt = new Date("2026-07-11T09:15:00+07:00");

describe("executive report export", () => {
  it("builds a portfolio report from the all-product scope", () => {
    const html = buildExecutiveReportHtml(deriveDashboard([...PRODUCT_IDS]), "portfolio", generatedAt);

    expect(html).toContain("Guardian Portfolio Health Report");
    expect(html).toContain("Products requiring attention");
    expect(html).toContain("Decision needed");
    expect(html).toContain("Synthetic demo data");
    expect(html).toContain("@page { size: A4");
  });

  it("builds a focused incident brief with actions and evidence", () => {
    const html = buildExecutiveReportHtml(deriveDashboard(["P-UV01"]), "focused", generatedAt);

    expect(html).toContain("Guardian Critical Incident Brief");
    expect(html).toContain("Top customer problems");
    expect(html).toContain("Recommended next steps");
    expect(html).toContain("Representative reports");
    expect(html).toContain("Guardian_Incident_GDN-SUN-001_2026-07-11");
  });

  it("returns false when the browser blocks the report preview", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    expect(openExecutiveReport(deriveDashboard(["P-UV01"]), "focused")).toBe(false);
  });
});
