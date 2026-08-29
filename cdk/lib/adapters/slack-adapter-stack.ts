// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.

// cdk/lib/adapters/slack-adapter-stack.ts
//
// Slack adapter AWS resources:
//
//   Inbound webhook routes (added via addSlackAdapter() helper):
//     POST /webhooks/slack/events → SlackEventsFn (adapters.slack.ingest.handler)
//     GET  /webhooks/slack/oauth/callback → SlackOAuthFn (adapters.slack.oauth.oauth_callback_handler)
//   Outbound:
//     SQS queue 'agentcomms-slack-outbound' + SlackOutboundFn (adapters.slack.outbound.handler)
//
//   IAM:
//     - SSM Parameter Store read for /agentcomms/*/adapters/slack/*
//     - SSM Parameter Store write for /agentcomms/*/adapters/slack/workspaces/* (OAuth complete)
//     - DynamoDB read/write (agentcomms table) — oauth state + channel updates
//     - Kinesis write (agentcomms-events)
//
// Usage pattern:
//   The SlackAdapterStack class creates the outbound queue + worker Lambda.
//   Call addSlackAdapter(apiStack, props) from agentcomms-api-stack.ts to attach
//   the two inbound webhook Lambdas to the existing API Gateway.
//
import * as path from 'path';
import { execSync } from 'child_process';
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Function as LambdaFn, Runtime, Code } from 'aws-cdk-lib/aws-lambda';
import { RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { PolicyStatement, Effect } from 'aws-cdk-lib/aws-iam';
import { Stream } from 'aws-cdk-lib/aws-kinesis';
import { ComparisonOperator, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';
import {
  RestApi, LambdaIntegration, AuthorizationType,
} from 'aws-cdk-lib/aws-apigateway';

// ── Props ──

export interface SlackAdapterStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
}

export interface AddSlackAdapterProps {
  table: Table;
  eventStream: Stream;
  api: RestApi;
}

// ── Helper: shared Lambda code asset (same pattern as other adapter stacks) ──

function makeLambdaCode(repoRoot: string): Code {
  return Code.fromAsset(repoRoot, {
    exclude: [
      'cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '.venv',
      '__pycache__', '*.pyc', '*.md', '.claude', '.github',
    ],
    bundling: {
      image: Runtime.PYTHON_3_12.bundlingImage,
      local: {
        tryBundle(outputDir: string): boolean {
          try {
            const tmpStage = `/tmp/agentcomms-slack-lambda-bundle-${Date.now()}`;
            execSync(`mkdir -p ${tmpStage}`);
            execSync(`cp -r ${repoRoot}/core ${tmpStage}/`);
            execSync(`cp -r ${repoRoot}/adapters ${tmpStage}/`);
            execSync(`cp ${repoRoot}/requirements-lambda.txt ${tmpStage}/`);
            execSync(
              `docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" \
                -v "${tmpStage}:/stage" \
                public.ecr.aws/sam/build-python3.12 \
                pip3 install -r /stage/requirements-lambda.txt -t /stage/ --no-cache-dir --disable-pip-version-check`,
              { stdio: 'inherit' },
            );
            execSync(`cp -r ${tmpStage}/. ${outputDir}/`);
            execSync(`rm -rf ${tmpStage}`);
            return true;
          } catch (e) {
            return false;
          }
        },
      },
      command: [
        'bash', '-c',
        [
          'cp -r /asset-input/core /asset-output/',
          'cp -r /asset-input/adapters /asset-output/',
          'pip3 install -r /asset-input/requirements-lambda.txt -t /asset-output/ --no-cache-dir --disable-pip-version-check',
        ].join(' && '),
      ],
    },
  });
}

// ── SSM policy helper ──

function slackSsmPolicy(): PolicyStatement {
  return new PolicyStatement({
    effect: Effect.ALLOW,
    actions: [
      'ssm:GetParameter',
      'ssm:PutParameter',
      'ssm:DeleteParameter',
    ],
    resources: [
      'arn:aws:ssm:*:*:parameter/agentcomms/*/adapters/slack/*',
    ],
  });
}

// ── addSlackAdapter: wire 2 inbound Lambdas onto the existing API Gateway ──
//
// Called from AgentCommsApiStack when enableSlack: true.
// Creates SlackEventsFn and SlackOAuthFn, then adds routes to the passed api.
//
export function addSlackAdapter(scope: Construct, props: AddSlackAdapterProps): {
  eventsFn: LambdaFn;
  oauthCallbackFn: LambdaFn;
} {
  const repoRoot = path.resolve(__dirname, '../../..');
  const code = makeLambdaCode(repoRoot);

  const commonEnv = {
    AGENTCOMMS_TABLE: props.table.tableName,
    AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
    AGENTCOMMS_ENV: 'prod',
  };

  // Slack Events Lambda — receives inbound events from Slack Events API
  const eventsFn = new LambdaFn(scope, 'SlackEventsFn', {
    runtime: Runtime.PYTHON_3_12,
    handler: 'adapters.slack.ingest.handler',
    code,
    timeout: Duration.seconds(10),   // Slack requires <3s but we have buffer for SSM cold start
    memorySize: 512,
    logRetention: RetentionDays.ONE_MONTH,
    environment: commonEnv,
  });
  props.table.grantReadWriteData(eventsFn);
  props.eventStream.grantWrite(eventsFn);
  eventsFn.addToRolePolicy(slackSsmPolicy());

  // Slack OAuth Callback Lambda — handles GET /webhooks/slack/oauth/callback
  const oauthCallbackFn = new LambdaFn(scope, 'SlackOAuthFn', {
    runtime: Runtime.PYTHON_3_12,
    handler: 'adapters.slack.oauth.oauth_callback_handler',
    code,
    timeout: Duration.seconds(30),
    memorySize: 512,
    logRetention: RetentionDays.ONE_MONTH,
    environment: commonEnv,
  });
  props.table.grantReadWriteData(oauthCallbackFn);
  oauthCallbackFn.addToRolePolicy(slackSsmPolicy());

  // Wire API Gateway routes (no authorizer — Slack calls these)
  const webhooks = props.api.root.addResource('webhooks');
  const slackResource = webhooks.addResource('slack');

  // POST /webhooks/slack/events
  const slackEvents = slackResource.addResource('events');
  slackEvents.addMethod('POST', new LambdaIntegration(eventsFn), {
    authorizationType: AuthorizationType.NONE,
  });

  // GET /webhooks/slack/oauth/callback
  const slackOauth = slackResource.addResource('oauth');
  const slackOauthCallback = slackOauth.addResource('callback');
  slackOauthCallback.addMethod('GET', new LambdaIntegration(oauthCallbackFn), {
    authorizationType: AuthorizationType.NONE,
  });

  return { eventsFn, oauthCallbackFn };
}

// ── SlackAdapterStack: outbound queue + worker ────────────────────────────────
//
// Creates the SQS outbound queue and the outbound Lambda consumer.
// The inbound API GW routes are NOT in this stack — they're wired by
// addSlackAdapter() into the existing AgentCommsApiStack.
//
export class SlackAdapterStack extends Stack {
  public readonly outboundFunction: LambdaFn;
  public readonly outboundQueue: Queue;
  public readonly outboundDlq: Queue;

  constructor(scope: Construct, id: string, props: SlackAdapterStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '../../..');
    const code = makeLambdaCode(repoRoot);

    const commonEnv = {
      AGENTCOMMS_TABLE: props.table.tableName,
      AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
    };

    // ── Outbound SQS + Lambda ──
    // Dead-letter queue captures messages that fail 5 delivery attempts.
    this.outboundDlq = new Queue(this, 'SlackOutboundDLQ', {
      queueName: 'agentcomms-slack-outbound-dlq',
      retentionPeriod: Duration.days(14),
    });
    this.outboundQueue = new Queue(this, 'SlackOutboundQueue', {
      queueName: 'agentcomms-slack-outbound',
      visibilityTimeout: Duration.seconds(60),
      deadLetterQueue: { queue: this.outboundDlq, maxReceiveCount: 5 },
    });
    // Alarm when any message lands in the DLQ (outbound send failing repeatedly).
    this.outboundDlq
      .metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(5), statistic: 'Maximum' })
      .createAlarm(this, 'SlackOutboundDLQAlarm', {
        alarmName: 'agentcomms-slack-outbound-dlq-not-empty',
        alarmDescription: 'agentcomms-slack-outbound DLQ has messages — outbound Slack delivery is failing.',
        threshold: 0,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });

    this.outboundFunction = new LambdaFn(this, 'SlackOutboundFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.slack.outbound.handler',
      code,
      timeout: Duration.seconds(30),
      memorySize: 512,
      logRetention: RetentionDays.ONE_MONTH,
      environment: commonEnv,
    });
    this.outboundFunction.addEventSource(new SqsEventSource(this.outboundQueue));
    props.table.grantReadWriteData(this.outboundFunction);
    props.eventStream.grantWrite(this.outboundFunction);
    this.outboundFunction.addToRolePolicy(slackSsmPolicy());
  }
}
