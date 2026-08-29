// SPDX-License-Identifier: Apache-2.0
import { Command } from "commander";
import { setMode, emit } from "../lib/ndjson.js";
import { readConfig } from "../lib/config.js";
import { describeStack } from "../lib/aws.js";

const STACKS = [
  "AgentCommsData",
  "AgentCommsEvents",
  "AgentCommsApi",
  "AgentCommsAdapters",
];

export function statusCommand(): Command {
  return new Command("status")
    .description("Show deployed stack status, SES identity, and channel health")
    .option("--domain <domain>", "domain to check (defaults to config)")
    .option("--region <region>", "AWS region (defaults to config)")
    .option("--profile <name>", "AWS named profile")
    .option("--json", "NDJSON output", false)
    .action(
      async (opts: {
        domain?: string;
        region?: string;
        profile?: string;
        json: boolean;
      }) => {
        if (opts.json) setMode("json");
        if (opts.profile) process.env.AWS_PROFILE = opts.profile;

        const config = readConfig();
        const region = opts.region ?? config.region ?? "us-east-1";
        const domain = opts.domain ?? config.domain;

        if (!domain) {
          emit({
            phase: "status",
            status: "fail",
            msg: "no domain configured; pass --domain or run agentcomms bootstrap first",
          });
          process.exit(1);
        }

        process.env.AWS_REGION = region;

        emit({ phase: "status", status: "running", msg: `checking ${domain} in ${region}` });

        const results: Record<string, string> = {};
        for (const stack of STACKS) {
          try {
            const s = await describeStack(stack, region);
            const st = s?.StackStatus ?? "NOT_FOUND";
            results[stack] = st;
            emit({
              phase: "status",
              check: stack,
              status: st.endsWith("_COMPLETE") && !st.startsWith("DELETE") ? "ok" : "warn",
              msg: st,
            });
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            results[stack] = "ERROR";
            emit({ phase: "status", check: stack, status: "fail", msg });
          }
        }

        const allOk = Object.values(results).every(
          (s) => s.endsWith("_COMPLETE") && !s.startsWith("DELETE")
        );

        emit({
          phase: "status",
          status: allOk ? "ok" : "warn",
          stacks: results,
          api_url: config.apiUrl ?? `https://api.${domain}/v1`,
          console_url: config.consoleUrl ?? `https://console.${domain}`,
          domain,
          region,
        });

        process.exit(allOk ? 0 : 1);
      }
    );
}
