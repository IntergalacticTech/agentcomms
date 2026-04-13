#!/usr/bin/env node
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

const app = new cdk.App();

const stage = app.node.tryGetContext("stage") ?? "dev";

const env: cdk.Environment = {
  account: "732770059798",
  region: "us-east-1",
};

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

const apiStack = new ApiStack(app, `VictoryMail-Api-${stage}`, {
  env,
  stage,
  table: dataStack.table,
  rawEmailBucket: dataStack.rawEmailBucket,
  bodiesBucket: dataStack.bodiesBucket,
  attachmentsBucket: dataStack.attachmentsBucket,
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

app.synth();
