import { describe, expect, it } from "vitest";
import { statusTone } from "./statusTone";

describe("statusTone", () => {
  it("classifies approval/success-like statuses", () => {
    expect(statusTone("approved")).toBe("success");
    expect(statusTone("succeeded")).toBe("success");
    expect(statusTone("human_approved")).toBe("success");
  });

  it("classifies rejection/failure-like statuses as danger", () => {
    expect(statusTone("rejected")).toBe("danger");
    expect(statusTone("failed")).toBe("danger");
    expect(statusTone("not_comparable")).toBe("danger");
  });

  it("classifies candidate/pending-like statuses as warning", () => {
    expect(statusTone("pending")).toBe("warning");
    expect(statusTone("candidate")).toBe("warning");
    expect(statusTone("changes_requested")).toBe("warning");
  });

  it("returns neutral for null/unknown values", () => {
    expect(statusTone(null)).toBe("neutral");
    expect(statusTone("something_entirely_unrecognized")).toBe("neutral");
  });
});
