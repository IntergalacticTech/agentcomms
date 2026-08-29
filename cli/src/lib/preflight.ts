// SPDX-License-Identifier: Apache-2.0
import { STSClient, GetCallerIdentityCommand } from "@aws-sdk/client-sts";
import { Route53Client, ListHostedZonesCommand } from "@aws-sdk/client-route-53";
import { SESv2Client, GetAccountCommand } from "@aws-sdk/client-sesv2";
import { emit } from "./ndjson.js";
import { spawnSync } from "node:child_process";

export interface PreflightResult {
  ok: boolean;
  account?: string;
  region: string;
  sesSandbox?: boolean;
  zoneId?: string;
  failures: Array<{ check: string; msg: string; fixHint?: string }>;
}

export const SUPPORTED_REGIONS = ["us-east-1", "us-west-2", "eu-west-1"];

async function checkAwsCreds(region: string): Promise<string | null> {
  try {
    const sts = new STSClient({ region });
    const resp = await sts.send(new GetCallerIdentityCommand({}));
    emit({
      phase: "preflight",
      check: "aws_credentials",
      status: "ok",
      msg: `account ${resp.Account}`,
    });
    return resp.Account ?? null;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    emit({ phase: "preflight", check: "aws_credentials", status: "fail", msg });
    return null;
  }
}

export function checkRegionSync(region: string): boolean {
  return SUPPORTED_REGIONS.includes(region);
}

async function checkRegion(region: string): Promise<boolean> {
  const ok = checkRegionSync(region);
  emit({
    phase: "preflight",
    check: "region",
    status: ok ? "ok" : "fail",
    msg: ok
      ? `SES-inbound region ${region}`
      : `region ${region} does not support SES inbound; use one of ${SUPPORTED_REGIONS.join(", ")}`,
  });
  return ok;
}

async function checkRoute53Zone(
  domain: string,
  region: string
): Promise<string | null> {
  try {
    const r53 = new Route53Client({ region });
    const resp = await r53.send(new ListHostedZonesCommand({}));
    const zone = (resp.HostedZones ?? []).find((z) => z.Name === `${domain}.`);
    if (!zone) {
      emit({
        phase: "preflight",
        check: "route53_zone",
        status: "fail",
        msg: `no Route 53 hosted zone for ${domain}`,
        fixHint: `aws route53 create-hosted-zone --name ${domain} --caller-reference $(date +%s)`,
      });
      return null;
    }
    emit({
      phase: "preflight",
      check: "route53_zone",
      status: "ok",
      msg: `zone ${zone.Id} found`,
    });
    return zone.Id ?? null;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    emit({ phase: "preflight", check: "route53_zone", status: "fail", msg });
    return null;
  }
}

async function checkSesAccount(region: string): Promise<boolean> {
  try {
    const ses = new SESv2Client({ region });
    const resp = await ses.send(new GetAccountCommand({}));
    const inSandbox = !resp.ProductionAccessEnabled;
    emit({
      phase: "preflight",
      check: "ses_account",
      status: inSandbox ? "warn" : "ok",
      msg: inSandbox
        ? "SES in sandbox; deploy will proceed but sending is limited to verified recipients"
        : "SES production access enabled",
    });
    return inSandbox;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    emit({ phase: "preflight", check: "ses_account", status: "warn", msg });
    return true;
  }
}

interface ToolSpec {
  bin: string;
  args: string[];
  re: RegExp;
  minimum: string;
}

function checkToolVersions(): boolean {
  const tools: ToolSpec[] = [
    { bin: "node", args: ["--version"], re: /v(\d+)\./, minimum: "20" },
    { bin: "python3", args: ["--version"], re: /Python (\d+)\.(\d+)/, minimum: "3.12" },
    { bin: "aws", args: ["--version"], re: /aws-cli\/(\d+)\./, minimum: "2" },
    { bin: "docker", args: ["info"], re: /Containers/, minimum: "" },
  ];
  let allOk = true;
  for (const tool of tools) {
    const result = spawnSync(tool.bin, tool.args, { encoding: "utf8" });
    if (result.status !== 0 && result.error) {
      emit({
        phase: "preflight",
        check: `tool_${tool.bin}`,
        status: "fail",
        msg: `${tool.bin} not installed or not functional`,
      });
      allOk = false;
      continue;
    }
    const out = ((result.stdout || "") + (result.stderr || "")).trim();
    emit({
      phase: "preflight",
      check: `tool_${tool.bin}`,
      status: result.status === 0 ? "ok" : "warn",
      msg: out.split("\n")[0] ?? tool.bin,
    });
  }
  return allOk;
}

export async function runPreflight(opts: {
  region: string;
  domain: string;
  account?: string;
}): Promise<PreflightResult> {
  const failures: PreflightResult["failures"] = [];

  const account = await checkAwsCreds(opts.region);
  if (!account) {
    failures.push({ check: "aws_credentials", msg: "could not get caller identity" });
  }
  if (opts.account && account && opts.account !== account) {
    failures.push({
      check: "aws_credentials",
      msg: `account mismatch: expected ${opts.account}, got ${account}`,
    });
  }

  const regionOk = await checkRegion(opts.region);
  if (!regionOk) {
    failures.push({ check: "region", msg: "region not supported" });
  }

  const zoneId = await checkRoute53Zone(opts.domain, opts.region);
  if (!zoneId) {
    failures.push({
      check: "route53_zone",
      msg: `no Route 53 zone for ${opts.domain}`,
    });
  }

  const sesSandbox = await checkSesAccount(opts.region);
  checkToolVersions();

  return {
    ok: failures.length === 0,
    account: account ?? undefined,
    region: opts.region,
    sesSandbox,
    zoneId: zoneId ?? undefined,
    failures,
  };
}
