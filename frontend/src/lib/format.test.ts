import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatCategory,
  formatChange,
  formatCount,
  formatHistorySource,
  formatScore,
} from "./format";

describe("formatCategory", () => {
  it("spells a category for reading", () => {
    expect(formatCategory("academic_processes")).toBe("Academic processes");
  });

  it("distinguishes a missing category from the general one", () => {
    // `null` is the classifier declining to place a question; `general` is it
    // placing one. Printing the same word for both would hide that.
    expect(formatCategory(null)).toBe("Uncategorised");
    expect(formatCategory("general")).toBe("General");
  });
});

describe("formatCount", () => {
  it("separates thousands so a count is not read as a year", () => {
    expect(formatCount(1204)).toBe("1,204");
  });
});

describe("formatChange", () => {
  it("reports a rise and a fall", () => {
    expect(formatChange(12, 9)).toBe("up 3");
    expect(formatChange(9, 12)).toBe("down 3");
  });

  it("says so when nothing moved", () => {
    expect(formatChange(9, 9)).toBe("No change");
  });

  it("returns nothing when there is no previous period", () => {
    // "+0 from 0" would claim a measured stillness the data does not support.
    expect(formatChange(9, 0)).toBeNull();
  });
});

describe("formatBytes", () => {
  it("gives one decimal in megabytes, because 1.5 MB is a size", () => {
    expect(formatBytes(1_572_864)).toBe("1.5 MB");
  });

  it("uses kilobytes below a megabyte", () => {
    expect(formatBytes(2048)).toBe("2 kB");
  });

  it("dashes a size the row does not have", () => {
    expect(formatBytes(null)).toBe("—");
  });
});

describe("formatScore", () => {
  it("shows a similarity as a percentage", () => {
    expect(formatScore(0.87)).toBe("87%");
  });

  it("dashes a missing score rather than calling it zero", () => {
    // A null score means only the keyword list found the chunk; there is no
    // cosine similarity to report, which is not the same as a similarity of 0.
    expect(formatScore(null)).toBe("—");
  });
});

describe("formatHistorySource", () => {
  it("names the page when the source has one", () => {
    expect(
      formatHistorySource({
        document_title: "Exam Schedule",
        page_number: 2,
        section_heading: null,
      }),
    ).toBe("Exam Schedule, page 2");
  });

  it("falls back to the heading for a document with no pages", () => {
    expect(
      formatHistorySource({
        document_title: "Hostel Rules",
        page_number: null,
        section_heading: "Quiet hours",
      }),
    ).toBe("Hostel Rules, Quiet hours");
  });

  it("says a deleted document is deleted rather than printing null", () => {
    expect(
      formatHistorySource({ document_title: null, page_number: null, section_heading: null }),
    ).toBe("Deleted document");
  });
});
