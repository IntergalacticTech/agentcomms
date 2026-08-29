// SPDX-License-Identifier: Apache-2.0
import { Command } from "commander";
import { createInterface } from "node:readline";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import { setMode, emit } from "../lib/ndjson.js";
import { readConfig } from "../lib/config.js";
import { cdkDestroy } from "../lib/cdk.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function repoRoot(): string {
  return resolve(__dirname, "..", "..", "..");
}

async function confirm(prompt: string): Promise<boolean> {
  return new Promise((resolve) => {
    const rl = createInterface({
      input: process.stdin,
      output: process.stderr,
    });
    rl.question(prompt, (answer) => {
      rl.close();
      resolve(answer.trim().toLowerCase() === "yes");
    });
  });
}

export function destroyCommand(): Command {
  return new Command("destroy")
    .description("Tear down all AgentComms CloudFormation stacks")
    .option("--yes", "skip confirmation prompt", false)
    .option("--region <region>", "AWS region (defaults to config)")
    .option("--profile <name>", "AWS named profile")
    .option("--json", "NDJSON output", false)
    .action(
      async (opts: {
        yes: boolean;
        region?: string;
        profile?: string;
        json: boolean;
      }) => {
        if (opts.json) setMode("json");
        if (opts.profile) process.env.AWS_PROFILE = opts.profile;

        const config = readConfig();
        const region = opts.region ?? config.region ?? "us-east-1";
        process.env.AWS_REGION = region;

        emit({
          phase: "destroy",
          status: "warn",
          msg: [
            "This will DELETE all AgentComms CloudFormation stacks.",
            "DynamoDB table, SNS/SQS/Kinesis resources will be DELETED.",
            "S3 buckets are RETAINED (delete manually if desired).",
            "This action cannot be undone.",
          ].join(" "),
        });

        if (!opts.yes) {
          const confirmed = await confirm(
            '\nType "yes" to confirm destruction: '
          );
          if (!confirmed) {
            emit({ phase: "destroy", status: "fail", msg: "Aborted — user did not confirm." });
            process.exit(1);
          }
        }

        emit({ phase: "destroy", status: "running", msg: "running cdk destroy --all --force" });
        const cdkDir = resolve(repoRoot(), "cdk");
        const result = cdkDestroy("--all", process.env as NodeJS.ProcessEnv, cdkDir);

        if (!result.ok) {
          emit({ phase: "destroy", status: "fail", msg: "cdk destroy failed; check CloudFormation console" });
          process.exit(2);
        }

        emit({
          phase: "destroy",
          status: "ok",
          msg: "All stacks destroyed. S3 buckets were retained — delete manually if needed.",
        });
        process.exit(0);
      }
    );
}
