// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { checkRegionSync, SUPPORTED_REGIONS } from "../lib/preflight.js";

describe("preflight region check", () => {
  it("accepts us-east-1", () => {
    expect(checkRegionSync("us-east-1")).toBe(true);
  });

  it("accepts us-west-2", () => {
    expect(checkRegionSync("us-west-2")).toBe(true);
  });

  it("accepts eu-west-1", () => {
    expect(checkRegionSync("eu-west-1")).toBe(true);
  });

  it("rejects us-east-2 (no SES inbound)", () => {
    expect(checkRegionSync("us-east-2")).toBe(false);
  });

  it("rejects ap-southeast-1", () => {
    expect(checkRegionSync("ap-southeast-1")).toBe(false);
  });

  it("rejects empty string", () => {
    expect(checkRegionSync("")).toBe(false);
  });

  it("SUPPORTED_REGIONS has exactly 3 entries", () => {
    expect(SUPPORTED_REGIONS).toHaveLength(3);
  });

  it("all SUPPORTED_REGIONS pass the check", () => {
    for (const region of SUPPORTED_REGIONS) {
      expect(checkRegionSync(region)).toBe(true);
    }
  });
});
