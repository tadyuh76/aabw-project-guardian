import { describe, expect, it } from "vitest";
import { cleanDisplayText } from "./displayText";

describe("cleanDisplayText", () => {
  it("removes presentation-only environment markers", () => {
    expect(cleanDisplayText("Demo product 3")).toBe("Product 3");
    expect(cleanDisplayText("Synthetic test sample insight")).toBe("Insight");
    expect(cleanDisplayText("Guardian demo: Giao hàng nhanh.")).toBe("Guardian: Giao hàng nhanh.");
  });

  it("removes generated record suffixes but preserves customer language", () => {
    expect(cleanDisplayText("Điểm thành viên sẽ được cộng sau bao lâu? Mẫu tổng hợp marketplace-current-55.")).toBe("Điểm thành viên sẽ được cộng sau bao lâu?");
    expect(cleanDisplayText("Tôi muốn test sản phẩm trên da nhạy cảm.")).toBe("Tôi muốn test sản phẩm trên da nhạy cảm.");
  });
});
