import { describe, expect, it } from "vitest";
import type { DashboardEvidence } from "../api/types";
import { categorizeProblem } from "./ReviewExplorer";

function evidence(overrides: Partial<DashboardEvidence>): DashboardEvidence {
  return {
    id: "feedback-1",
    productId: null,
    text: "Bên mình có tuyển nhân viên bán hàng k ạ",
    sourceGroup: "social",
    sourcePlatform: "tiktok",
    sourceUrl: null,
    timestamp: null,
    confidence: null,
    stance: null,
    topic: "other",
    subtopic: "other",
    sentiment: "neutral",
    ...overrides,
  };
}

describe("categorizeProblem", () => {
  it("uses backend taxonomy before falling back to text heuristics", () => {
    expect(categorizeProblem(evidence({ topic: "other", subtopic: "other" }))).toBe("Other");
    expect(categorizeProblem(evidence({ topic: "product_quality_authenticity", subtopic: "packaging_quality" }))).toBe("Packaging Quality");
    expect(categorizeProblem(evidence({ topic: null, subtopic: null, text: "Watsons delivery was late." }))).toBe("Late delivery");
  });
});
