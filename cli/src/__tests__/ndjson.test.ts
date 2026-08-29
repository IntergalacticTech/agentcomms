// SPDX-License-Identifier: Apache-2.0
import { emit, setMode, StatusEvent } from "../lib/ndjson.js";

describe("ndjson emit", () => {
  let stdoutOutput: string[] = [];
  const originalWrite = process.stdout.write.bind(process.stdout);

  beforeEach(() => {
    stdoutOutput = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (process.stdout.write as any) = (chunk: string | Uint8Array) => {
      if (typeof chunk === "string") stdoutOutput.push(chunk);
      return true;
    };
  });

  afterEach(() => {
    process.stdout.write = originalWrite;
    setMode("human"); // reset
  });

  it("emits valid JSON line in json mode", () => {
    setMode("json");
    const event: StatusEvent = { phase: "test", status: "ok", msg: "hello" };
    emit(event);
    expect(stdoutOutput).toHaveLength(1);
    const line = stdoutOutput[0];
    expect(line.endsWith("\n")).toBe(true);
    const parsed = JSON.parse(line.trim());
    expect(parsed).toMatchObject({ phase: "test", status: "ok", msg: "hello" });
  });

  it("emits exactly one JSON line with newline terminator", () => {
    setMode("json");
    emit({ phase: "deploy", status: "running", stack: "AgentCommsData", progress: 0.3 });
    expect(stdoutOutput).toHaveLength(1);
    const lines = stdoutOutput[0].split("\n").filter(Boolean);
    expect(lines).toHaveLength(1);
  });

  it("JSON output includes all provided fields", () => {
    setMode("json");
    emit({
      phase: "seed",
      status: "ok",
      org_id: "org_01H",
      admin_api_key: "ak_live_test",
      note: "shown once",
    });
    const parsed = JSON.parse(stdoutOutput[0].trim());
    expect(parsed.org_id).toBe("org_01H");
    expect(parsed.admin_api_key).toBe("ak_live_test");
    expect(parsed.note).toBe("shown once");
  });

  it("does not write to stdout in human mode", () => {
    setMode("human");
    emit({ phase: "test", status: "ok", msg: "should go to stderr" });
    expect(stdoutOutput).toHaveLength(0);
  });
});
