import { describe, expect, it } from "vitest";
import { aggregateRatingTrend } from "./Dashboard";
import type { DashboardProduct, ProductRatingTrendPoint } from "../api/types";

function product(points: ProductRatingTrendPoint[]): DashboardProduct {
  return { ratingTrend: points } as DashboardProduct;
}

describe("aggregateRatingTrend", () => {
  it("aggregates observed points before creating one platform forecast", () => {
    const points = aggregateRatingTrend([
      product([
        { date: "2026-06-01", platform: "Shopee", averageRating: 4, count: 10, predicted: false },
        { date: "2026-06-08", platform: "Shopee", averageRating: 4.2, count: 10, predicted: false },
        { date: "2026-06-15", platform: "Shopee", averageRating: 4.4, count: 10, predicted: true },
      ]),
      product([
        { date: "2026-06-01", platform: "Shopee", averageRating: 5, count: 2, predicted: false },
        { date: "2026-06-08", platform: "Shopee", averageRating: 4.8, count: 2, predicted: false },
        { date: "2026-06-15", platform: "Shopee", averageRating: 4.6, count: 2, predicted: true },
      ]),
    ]);

    const observed = points.filter((point) => !point.predicted);
    const predicted = points.filter((point) => point.predicted);
    expect(observed).toHaveLength(2);
    expect(predicted).toHaveLength(1);
    expect(observed[0]?.averageRating).toBeCloseTo(4.1667, 3);
    expect(predicted[0]).toMatchObject({ platform: "Shopee", date: "2026-06-15", predicted: true });
  });
});
