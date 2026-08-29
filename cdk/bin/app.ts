#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.

import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { DataStack } from "../lib/stacks/data-stack";
import { EmailStack } from "../lib/stacks/email-stack";
import { QueueStack } from "../lib/stacks/queue-stack";
import { ApiStack } from "../lib/stacks/api-stack";
import { AuthStack } from "../lib/stacks/auth-stack";
import { CicdStack } from "../lib/stacks/cicd-stack";
import { ConsoleStack } from "../lib/stacks/console-stack";
import { MonitoringStack } from "../lib/stacks/monitoring-stack";
import { LandingStack } from "../lib/stacks/landing-stack";
import { AgentCommsDataStack } from "../lib/stacks/agentcomms-data-stack";
import { AgentCommsEventsStack } from "../lib/stacks/agentcomms-events-stack";
import { AgentCommsApiStack } from "../lib/stacks/agentcomms-api-stack";
import { AgentCommsAdaptersStack } from "../lib/stacks/agentcomms-adapters-stack";

const app = new cdk.App();

const stage = app.node.tryGetContext("stage") ?? "dev";
const account =
  app.node.tryGetContext("account") ??
  process.env.CDK_DEFAULT_ACCOUNT ??
  process.env.AWS_ACCOUNT_ID;
const region =
  app.node.tryGetContext("region") ??
  process.env.CDK_DEFAULT_REGION ??
  process.env.AWS_REGION ??
  "us-east-1";
const env: cdk.Environment = account ? { account, region } : { region };

function flag(name: string, defaultValue: boolean): boolean {
  const raw = app.node.tryGetContext(name) ?? process.env[`AGENTCOMMS_${name.toUpperCase()}`];
  if (raw === undefined || raw === null || raw === "") return defaultValue;
  return ["1", "true", "yes", "y"].includes(String(raw).toLowerCase());
}

function isChannelEnabled(name: string): boolean {
  if (process.env[`AGENTCOMMS_SKIP_${name.toUpperCase()}`] === "1") {
    return false;
  }
  return flag(`enable${name[0].toUpperCase()}${name.slice(1)}`, true);
}

const deployLegacy = flag("deployLegacy", false);
const deployAgentComms = flag("deployAgentComms", true);
const agentCommsEnvName = app.node.tryGetContext("envName") ?? stage;
const agentCommsDomain =
  app.node.tryGetContext("domain") ??
  process.env.AGENTCOMMS_DOMAIN ??
  "agentcomms.dev";

if (deployLegacy) {
  const dataStack = new DataStack(app, `VictoryMail-Data-${stage}`, {
    env,
    stage,
  });

  const emailStack = new EmailStack(app, `VictoryMail-Email-${stage}`, {
    env,
    stage,
  });

  const queueStack = new QueueStack(app, `VictoryMail-Queue-${stage}`, {
    env,
    stage,
  });

  const authStack = new AuthStack(app, `VictoryMail-Auth-${stage}`, {
    env,
    stage,
  });

  new ApiStack(app, `VictoryMail-Api-${stage}`, {
    env,
    stage,
    table: dataStack.table,
    rawEmailBucket: dataStack.rawEmailBucket,
    bodiesBucket: dataStack.bodiesBucket,
    attachmentsBucket: dataStack.attachmentsBucket,
    vaultBucket: dataStack.vaultBucket,
    sendQueue: queueStack.sendQueue,
    webhookQueue: queueStack.webhookQueue,
    bounceTopic: emailStack.bounceTopic,
    complaintTopic: emailStack.complaintTopic,
    deliveryTopic: emailStack.deliveryTopic,
    userPoolId: authStack.userPool.userPoolId,
    userPoolClientId: authStack.userPoolClient.userPoolClientId,
  });

  new CicdStack(app, `VictoryMail-CICD-${stage}`, { env, stage });
  new ConsoleStack(app, `VictoryMail-Console-${stage}`, { env, stage });
  new MonitoringStack(app, `VictoryMail-Monitoring-${stage}`, { env, stage });
  new LandingStack(app, `VictoryMail-Landing-${stage}`, { env, stage });
}

if (deployAgentComms) {
  const agentCommsData = new AgentCommsDataStack(app, "AgentCommsData", {
    env,
    envName: agentCommsEnvName,
  });

  const agentCommsEvents = new AgentCommsEventsStack(app, "AgentCommsEvents", {
    env,
  });

  new AgentCommsApiStack(app, "AgentCommsApi", {
    env,
    table: agentCommsData.table,
    eventStream: agentCommsEvents.eventStream,
    rawInboundBucket: agentCommsData.rawInboundBucket,
    bodiesBucket: agentCommsData.bodiesBucket,
    attachmentsBucket: agentCommsData.attachmentsBucket,
    enableSlack: isChannelEnabled("slack"),
    enableTelegram: isChannelEnabled("telegram"),
  });

  new AgentCommsAdaptersStack(app, "AgentCommsAdapters", {
    env,
    table: agentCommsData.table,
    eventStream: agentCommsEvents.eventStream,
    rawInboundBucket: agentCommsData.rawInboundBucket,
    bodiesBucket: agentCommsData.bodiesBucket,
    attachmentsBucket: agentCommsData.attachmentsBucket,
    inboundDomains: [agentCommsDomain],
    enableSms: isChannelEnabled("sms"),
    enablePush: isChannelEnabled("push"),
    enableSlack: isChannelEnabled("slack"),
    enableTelegram: isChannelEnabled("telegram"),
  });
}

app.synth();
