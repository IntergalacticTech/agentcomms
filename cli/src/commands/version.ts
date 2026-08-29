// SPDX-License-Identifier: Apache-2.0
import { Command } from "commander";
import { emit } from "../lib/ndjson.js";

const VERSION = "0.1.0";

export function versionCommand(): Command {
  return new Command("version")
    .description("Print CLI version")
    .option("--json", "NDJSON output", false)
    .action((opts: { json: boolean }) => {
      if (opts.json) {
        process.stdout.write(JSON.stringify({ phase: "version", version: VERSION }) + "\n");
      } else {
        emit({ phase: "version", status: "ok", msg: `agentcomms ${VERSION}` });
      }
    });
}
