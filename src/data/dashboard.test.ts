import { describe, expect, it } from "vitest";
import {
  PRODUCTS,
  PRODUCT_IDS,
  deriveDashboard,
  parseProductSelection,
  serializeProductSelection,
} from "./dashboard";

describe("deriveDashboard", () => {
  it("ships a broad mock catalog with realistic review volume", () => {
    expect(PRODUCTS).toHaveLength(12);
    expect(PRODUCTS.reduce((total, product) => total + product.ratingCount, 0)).toBe(68420);
    expect(new Set(PRODUCTS.map((product) => product.category)).size).toBeGreaterThanOrEqual(8);
    expect(PRODUCTS.every((product) => product.rating >= 4 && product.ratingCount >= 2500)).toBe(true);
  });

  it("preserves the comprehensive all-product fixture", () => {
    const data = deriveDashboard([...PRODUCT_IDS]);

    expect(data.currentComplaints).toBe(337);
    expect(data.currentReviews).toBe(5760);
    expect(data.complaintShare).toBeCloseTo(5.850694, 5);
    expect(data.baselineComplaints).toBe(3820);
    expect(data.baselineReviews).toBe(153200);
    expect(data.baselineShare).toBeCloseTo(2.493473, 5);
    expect(data.velocity).toBeCloseTo(2.346404, 5);
    expect(data.status).toBe("critical");
    expect(data.competitors[0]).toMatchObject({ retailer: "hasaki", complaints: 163, reviews: 5980 });
    expect(data.competitors[1]).toMatchObject({ retailer: "watsons", complaints: 140, reviews: 5710 });
  });

  it("derives a consistent single-product cohort", () => {
    const data = deriveDashboard(["P-UV01"]);

    expect(data.currentComplaints).toBe(126);
    expect(data.currentReviews).toBe(480);
    expect(data.complaintShare).toBeCloseTo(26.25, 5);
    expect(data.velocity).toBeCloseTo(6.890625, 5);
    expect(data.status).toBe("critical");
    expect(data.affectedProducts.map((product) => product.id)).toEqual(["P-UV01"]);
    expect(data.evidence.every((item) => item.productId === "P-UV01")).toBe(true);
    expect(data.hypotheses[0]?.id).toBe("H-PUMP");
    expect(data.recommendedAction).toMatchObject({
      playbookId: "PB-PACKAGING-SEAL",
      owner: "E-commerce Operations",
      priority: "Critical",
      monitoringWindowHours: 48,
    });
    expect(data.recommendedAction?.successTargetShare).toBeCloseTo(4.5714, 3);
    expect(data.recommendedAction?.steps).toHaveLength(3);
  });

  it("aggregates multiple products by counts instead of averaging shares", () => {
    const data = deriveDashboard(["P-UV01", "P-UV02"]);

    expect(data.currentComplaints).toBe(230);
    expect(data.currentReviews).toBe(920);
    expect(data.complaintShare).toBeCloseTo(25, 5);
    expect(data.velocity).toBeCloseTo(6.76, 2);
    expect(data.selectedProducts).toHaveLength(2);
  });

  it("returns a real empty cohort", () => {
    const data = deriveDashboard([]);

    expect(data.status).toBeNull();
    expect(data.complaintShare).toBeNull();
    expect(data.affectedProducts).toEqual([]);
    expect(data.evidence).toEqual([]);
    expect(data.hypotheses).toEqual([]);
    expect(data.recommendedAction).toBeNull();
  });

  it("keeps derived surfaces inside the selected cohort", () => {
    const selected = ["P-CL01", "P-MO01"] as const;
    const data = deriveDashboard([...selected]);

    expect(data.currentComplaints).toBe(30);
    expect(data.currentReviews).toBe(1130);
    expect(data.status).toBe("watch");
    expect(data.affectedProducts.reduce((total, product) => total + product.current.complaints, 0)).toBe(30);
    expect(data.evidence.every((item) => selected.includes(item.productId as typeof selected[number]))).toBe(true);
    expect(data.activities.every((item) => selected.includes(item.productId as typeof selected[number]))).toBe(true);
  });
});

describe("product selection URL contract", () => {
  it("defaults to all products", () => {
    expect(parseProductSelection("")).toEqual(PRODUCT_IDS);
    expect(parseProductSelection("?products=all")).toEqual(PRODUCT_IDS);
  });

  it("keeps explicit empty selection empty", () => {
    expect(parseProductSelection("?products=")).toEqual([]);
  });

  it("ignores unknown IDs and normalizes catalog order", () => {
    expect(parseProductSelection("?products=P-SE01,UNKNOWN,P-UV01,P-SE01")).toEqual([
      "P-UV01",
      "P-SE01",
    ]);
  });

  it("serializes all, empty and multi-select states", () => {
    expect(serializeProductSelection([...PRODUCT_IDS])).toBe("all");
    expect(serializeProductSelection([])).toBe("");
    expect(serializeProductSelection(["P-MO01", "P-UV01"])).toBe("P-UV01,P-MO01");
  });
});
