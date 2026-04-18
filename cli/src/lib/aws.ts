// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { STSClient, GetCallerIdentityCommand } from "@aws-sdk/client-sts";
import {
  Route53Client,
  ListHostedZonesCommand,
  HostedZone,
} from "@aws-sdk/client-route-53";
import { SESv2Client, GetAccountCommand } from "@aws-sdk/client-sesv2";
import {
  CloudFormationClient,
  DescribeStacksCommand,
  Stack,
} from "@aws-sdk/client-cloudformation";
import {
  SSMClient,
  GetParameterCommand,
  PutParameterCommand,
} from "@aws-sdk/client-ssm";

export interface CallerIdentity {
  account: string;
  arn: string;
  userId: string;
}

export async function getCallerIdentity(region: string): Promise<CallerIdentity> {
  const sts = new STSClient({ region });
  const resp = await sts.send(new GetCallerIdentityCommand({}));
  return {
    account: resp.Account ?? "",
    arn: resp.Arn ?? "",
    userId: resp.UserId ?? "",
  };
}

export async function findHostedZone(
  domain: string,
  region: string
): Promise<HostedZone | null> {
  const r53 = new Route53Client({ region });
  const resp = await r53.send(new ListHostedZonesCommand({}));
  const zone = (resp.HostedZones ?? []).find((z) => z.Name === `${domain}.`);
  return zone ?? null;
}

export interface SesAccountStatus {
  inSandbox: boolean;
  sendingEnabled: boolean;
}

export async function getSesAccountStatus(region: string): Promise<SesAccountStatus> {
  const ses = new SESv2Client({ region });
  const resp = await ses.send(new GetAccountCommand({}));
  return {
    inSandbox: !resp.ProductionAccessEnabled,
    sendingEnabled: resp.SendingEnabled ?? false,
  };
}

export async function describeStack(
  stackName: string,
  region: string
): Promise<Stack | null> {
  const cf = new CloudFormationClient({ region });
  try {
    const resp = await cf.send(
      new DescribeStacksCommand({ StackName: stackName })
    );
    return resp.Stacks?.[0] ?? null;
  } catch {
    return null;
  }
}

export async function getSsmParameter(
  name: string,
  region: string
): Promise<string | null> {
  const ssm = new SSMClient({ region });
  try {
    const resp = await ssm.send(
      new GetParameterCommand({ Name: name, WithDecryption: true })
    );
    return resp.Parameter?.Value ?? null;
  } catch {
    return null;
  }
}

export async function putSsmParameter(
  name: string,
  value: string,
  region: string,
  secure = false
): Promise<void> {
  const ssm = new SSMClient({ region });
  await ssm.send(
    new PutParameterCommand({
      Name: name,
      Value: value,
      Type: secure ? "SecureString" : "String",
      Overwrite: true,
    })
  );
}
