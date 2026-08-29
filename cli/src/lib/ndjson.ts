// SPDX-License-Identifier: Apache-2.0
import chalk from "chalk";

export interface StatusEvent {
  phase: string;
  status?: "ok" | "running" | "waiting" | "warn" | "fail";
  check?: string;
  stack?: string;
  progress?: number;
  msg?: string;
  [key: string]: unknown;
}

let mode: "json" | "human" = "human";

export function setMode(m: "json" | "human"): void {
  mode = m;
}

export function getMode(): "json" | "human" {
  return mode;
}

export function emit(event: StatusEvent): void {
  if (mode === "json") {
    process.stdout.write(JSON.stringify(event) + "\n");
  } else {
    const icon =
      {
        ok: chalk.green("✓"),
        running: chalk.blue("●"),
        waiting: chalk.yellow("…"),
        warn: chalk.yellow("!"),
        fail: chalk.red("✗"),
      }[event.status ?? "running"] ?? chalk.gray("·");
    const phase = chalk.cyan(event.phase.padEnd(20));
    const check = event.check ? chalk.dim(event.check) + " " : "";
    const msg = event.msg ?? "";
    process.stderr.write(`${icon} ${phase} ${check}${msg}\n`);
  }
}
