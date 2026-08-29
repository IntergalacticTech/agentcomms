// SPDX-License-Identifier: Apache-2.0
import { spawnSync, SpawnSyncReturns } from "node:child_process";
import { emit } from "./ndjson.js";

export interface CdkResult {
  ok: boolean;
  stdout: string;
  stderr: string;
  exitCode: number;
}

export function cdkBootstrap(
  account: string,
  region: string,
  env: NodeJS.ProcessEnv,
  quiet: boolean
): CdkResult {
  emit({ phase: "cdk_bootstrap", status: "running", msg: `bootstrapping aws://${account}/${region}` });
  const result: SpawnSyncReturns<string> = spawnSync(
    "npx",
    ["cdk", "bootstrap", `aws://${account}/${region}`],
    {
      stdio: quiet ? "pipe" : ["inherit", "pipe", "inherit"],
      encoding: "utf8",
      env,
    }
  );
  const ok = result.status === 0;
  emit({
    phase: "cdk_bootstrap",
    status: ok ? "ok" : "fail",
    msg: ok ? "bootstrap complete" : "cdk bootstrap failed",
  });
  return {
    ok,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    exitCode: result.status ?? 1,
  };
}

export function cdkDeploy(
  stacks: string[],
  env: NodeJS.ProcessEnv,
  cdkDir: string,
  quiet: boolean
): CdkResult {
  const args = [
    "cdk",
    "deploy",
    ...stacks,
    "--require-approval",
    "never",
    "--concurrency",
    "2",
  ];
  const result: SpawnSyncReturns<string> = spawnSync("npx", args, {
    stdio: quiet ? "pipe" : ["inherit", "pipe", "inherit"],
    encoding: "utf8",
    env,
    cwd: cdkDir,
  });
  const ok = result.status === 0;
  return {
    ok,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    exitCode: result.status ?? 1,
  };
}

export function cdkDestroy(
  stackGlob: string,
  env: NodeJS.ProcessEnv,
  cdkDir: string
): CdkResult {
  const result: SpawnSyncReturns<string> = spawnSync(
    "npx",
    ["cdk", "destroy", stackGlob, "--force"],
    {
      stdio: "inherit",
      encoding: "utf8",
      env,
      cwd: cdkDir,
    }
  );
  const ok = result.status === 0;
  return {
    ok,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    exitCode: result.status ?? 1,
  };
}
