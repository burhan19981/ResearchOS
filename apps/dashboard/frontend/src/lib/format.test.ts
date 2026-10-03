import { describe, expect, it } from "vitest";
import { formatBytes, formatDateTime, formatDuration, humanizeToken } from "./format";

describe("humanizeToken", () => {
  it("converts an ALL_CAPS_TOKEN into Title Case words", () => {
    expect(humanizeToken("STAGE_01_IDEA")).toBe("Stage 01 Idea");
    expect(humanizeToken("not_comparable")).toBe("Not Comparable");
  });

  it("returns an em dash for null/undefined/empty", () => {
    expect(humanizeToken(null)).toBe("—");
    expect(humanizeToken(undefined)).toBe("—");
    expect(humanizeToken("")).toBe("—");
  });
});

describe("formatDuration", () => {
  it("formats sub-minute durations in seconds", () => {
    expect(formatDuration(12.345)).toBe("12.3s");
  });

  it("formats multi-minute durations", () => {
    expect(formatDuration(125)).toBe("2m 5s");
  });

  it("returns an em dash for null", () => {
    expect(formatDuration(null)).toBe("—");
  });
});

describe("formatBytes", () => {
  it("formats bytes into the largest sensible unit", () => {
    expect(formatBytes(500)).toBe("500 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("formatDateTime", () => {
  it("returns an em dash for a missing value", () => {
    expect(formatDateTime(null)).toBe("—");
  });

  it("returns the original string for an unparseable value", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});
