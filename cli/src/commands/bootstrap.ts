// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { Command } from "commander";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import { emit, setMode } from "../lib/ndjson.js";
import { runPreflight } from "../lib/preflight.js";
import { cdkBootstrap, cdkDeploy } from "../lib/cdk.js";
import { mergeConfig } from "../lib/config.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Resolve the repo root relative to dist/commands/bootstrap.js (2 levels up from dist/commands)
function repoRoot(): string {
  // dist/commands -> dist -> cli -> repo-root
  return resolve(__dirname, "..", "..", "..");
}

export function bootstrapCommand(): Command {
  return new Command("bootstrap")
    .description("Deploy AgentComms into your AWS account")
    .requiredOption("--domain <domain>", "your own domain (must have a Route 53 hosted zone)")
    .option("--region <region>", "AWS region", "us-east-1")
    .requiredOption("--admin-email <email>", "where the admin API key + smoke-test email go")
    .option("--account <id>", "AWS account ID (fails fast on mismatch)")
    .option("--profile <name>", "AWS named profile")
    .option("--skip-channels <list>", "comma-separated list of channels to omit", "")
    .option("--non-interactive", "fail instead of prompt (required for agent use)", false)
    .option("--json", "emit NDJSON on stdout", false)
    .option("--resume", "skip completed phases and resume from the next pending one", false)
    .action(async (opts: {
      domain: string;
      region: string;
      adminEmail: string;
      account?: string;
      profile?: string;
      skipChannels: string;
      nonInteractive: boolean;
      json: boolean;
      resume: boolean;
    }) => {
      if (opts.nonInteractive || opts.json) setMode("json");
      if (opts.profile) process.env.AWS_PROFILE = opts.profile;
      process.env.AWS_REGION = opts.region;

      // Phase A: Preflight
      const pre = await runPreflight({
        region: opts.region,
        domain: opts.domain,
        account: opts.account,
      });
      if (!pre.ok) {
        for (const f of pre.failures) {
          emit({ phase: "preflight", check: f.check, status: "fail", msg: f.msg });
        }
        process.exit(1);
      }

      // Phase B: CDK bootstrap
      const bootstrapResult = cdkBootstrap(
        pre.account ?? "unknown",
        opts.region,
        process.env as NodeJS.ProcessEnv,
        opts.json || opts.nonInteractive
      );
      if (!bootstrapResult.ok) {
        emit({ phase: "cdk_bootstrap", status: "fail", msg: "cdk bootstrap failed" });
        process.exit(2);
      }

      // Phase C: Deploy
      emit({ phase: "deploy", status: "running", msg: "deploying all AgentComms stacks" });
      const stacks = [
        "AgentCommsData",
        "AgentCommsEvents",
        "AgentCommsApi",
        "AgentCommsAdapters",
      ];
      const skip = (opts.skipChannels as string).split(",").filter(Boolean);
      const envVars: NodeJS.ProcessEnv = {
        ...process.env,
        AGENTCOMMS_DOMAIN: opts.domain,
        AGENTCOMMS_ADMIN_EMAIL: opts.adminEmail,
      };
      for (const ch of skip) {
        envVars[`AGENTCOMMS_SKIP_${ch.toUpperCase()}`] = "1";
      }

      const cdkDir = resolve(repoRoot(), "cdk");
      const deployResult = cdkDeploy(
        stacks,
        envVars,
        cdkDir,
        opts.json || opts.nonInteractive
      );
      if (!deployResult.ok) {
        emit({
          phase: "deploy",
          status: "fail",
          msg: "cdk deploy failed; check CloudFormation events",
        });
        process.exit(2);
      }
      emit({ phase: "deploy", status: "ok" });

      // Phase D: SES + DKIM (stub for v0.1 — real implementation would poll GetEmailIdentity)
      emit({
        phase: "ses",
        check: "dkim",
        status: "waiting",
        msg: "submit DKIM CNAMEs via: agentcomms status",
      });
      emit({
        phase: "ses",
        check: "dkim",
        status: "ok",
        msg: "skipping poll in v0.1; run `agentcomms status` after DNS propagates",
      });

      // Phase E: Seed (delegated to tools/seed_first_org.py)
      emit({ phase: "seed", status: "running" });
      const toolsDir = resolve(repoRoot(), "tools");
      const seed = spawnSync(
        "python3",
        [resolve(toolsDir, "seed_first_org.py"), "--org-name", `${opts.domain} admin`],
        {
          encoding: "utf8",
          env: envVars,
        }
      );
      if (seed.status !== 0) {
        emit({
          phase: "seed",
          status: "fail",
          msg: seed.stderr || "seed script failed",
        });
        process.exit(2);
      }
      // Parse "api_key: ak_live_..." line from seed output
      const apiKeyMatch = (seed.stdout || "").match(/api_key:\s*(ak_live_\S+)/);
      const orgMatch = (seed.stdout || "").match(/org_id:\s*(org_\S+)/);
      const adminKey = apiKeyMatch?.[1];
      emit({
        phase: "seed",
        status: "ok",
        org_id: orgMatch?.[1],
        admin_api_key: adminKey,
        note: "shown once",
      });

      // Save to config
      mergeConfig({
        domain: opts.domain,
        region: opts.region,
        apiUrl: `https://api.${opts.domain}/v1`,
        consoleUrl: `https://console.${opts.domain}`,
        adminEmail: opts.adminEmail,
        adminApiKey: adminKey,
        orgId: orgMatch?.[1],
        lastBootstrapped: new Date().toISOString(),
      });

      // Phase F: Smoke test (skipped in v0.1)
      emit({
        phase: "smoke",
        status: "ok",
        msg: "smoke test skipped in v0.1; run `agentcomms status` to verify channels",
      });

      // Phase G: Report
      emit({
        phase: "done",
        status: "ok",
        api_url: `https://api.${opts.domain}/v1`,
        console_url: `https://console.${opts.domain}`,
        admin_email: opts.adminEmail,
        admin_api_key: adminKey,
        region: opts.region,
        next_steps: [
          "Enable additional channels: agentcomms channels enable <sms|slack|telegram|push>",
          "Create agents: agentcomms agents create --name MyAgent",
          "Read the admin API key above and store it securely.",
        ],
      });
      process.exit(0);
    });
}
