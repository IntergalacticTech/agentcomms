// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { Command } from "commander";
import { setMode } from "../lib/ndjson.js";
import { runPreflight } from "../lib/preflight.js";

export function doctorCommand(): Command {
  return new Command("doctor")
    .description("Run preflight checks without deploying anything")
    .requiredOption("--domain <domain>", "domain to validate DNS for")
    .option("--region <region>", "AWS region", "us-east-1")
    .option("--account <id>", "AWS account ID")
    .option("--profile <name>", "AWS named profile")
    .option("--json", "NDJSON output", false)
    .action(
      async (opts: {
        domain: string;
        region: string;
        account?: string;
        profile?: string;
        json: boolean;
      }) => {
        if (opts.json) setMode("json");
        if (opts.profile) process.env.AWS_PROFILE = opts.profile;
        process.env.AWS_REGION = opts.region;
        const result = await runPreflight({
          region: opts.region,
          domain: opts.domain,
          account: opts.account,
        });
        process.exit(result.ok ? 0 : 1);
      }
    );
}
