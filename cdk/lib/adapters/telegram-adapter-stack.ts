// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

// cdk/lib/adapters/telegram-adapter-stack.ts
//
// Telegram adapter AWS resources:
//
//   Inbound webhook route (added via addTelegramAdapter() helper):
//     POST /webhooks/telegram/{token_hash} → TelegramIngestFn (adapters.telegram.ingest.handler)
//   Outbound:
//     SQS queue 'agentcomms-telegram-outbound' + TelegramOutboundFn (adapters.telegram.outbound.handler)
//
//   IAM:
//     - SSM Parameter Store read/write for /agentcomms/*/adapters/telegram/tokens/*
//     - DynamoDB read/write (agentcomms table)
//     - Kinesis write (agentcomms-events)
//
// Usage pattern:
//   The TelegramAdapterStack class creates the outbound queue + worker Lambda.
//   Call addTelegramAdapter(apiStack, props) from agentcomms-api-stack.ts to attach
//   the inbound webhook Lambda to the existing API Gateway.
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

export interface TelegramAdapterStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
}

export interface AddTelegramAdapterProps {
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
            const tmpStage = `/tmp/agentcomms-telegram-lambda-bundle-${Date.now()}`;
            execSync(`mkdir -p ${tmpStage}`);
            execSync(`cp -r ${repoRoot}/core ${tmpStage}/`);
            execSync(`cp -r ${repoRoot}/adapters ${tmpStage}/`);
            execSync(`cp ${repoRoot}/requirements-lambda.txt ${tmpStage}/`);
            execSync(
              `docker run --rm --platform linux/amd64 \
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

function telegramSsmPolicy(): PolicyStatement {
  return new PolicyStatement({
    effect: Effect.ALLOW,
    actions: [
      'ssm:GetParameter',
      'ssm:PutParameter',
      'ssm:DeleteParameter',
    ],
    resources: [
      'arn:aws:ssm:*:*:parameter/agentcomms/*/adapters/telegram/tokens/*',
    ],
  });
}

// ── addTelegramAdapter: wire inbound Lambda onto the existing API Gateway ──
//
// Called from AgentCommsApiStack when enableTelegram: true.
// Creates TelegramIngestFn, then adds the webhook route to the passed api.
//
export function addTelegramAdapter(scope: Construct, props: AddTelegramAdapterProps): {
  ingestFn: LambdaFn;
} {
  const repoRoot = path.resolve(__dirname, '../../..');
  const code = makeLambdaCode(repoRoot);

  const commonEnv = {
    AGENTCOMMS_TABLE: props.table.tableName,
    AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
    AGENTCOMMS_ENV: 'prod',
  };

  // Telegram Ingest Lambda — receives webhook updates from Telegram Bot API
  const ingestFn = new LambdaFn(scope, 'TelegramIngestFn', {
    runtime: Runtime.PYTHON_3_12,
    handler: 'adapters.telegram.ingest.handler',
    code,
    timeout: Duration.seconds(10),
    memorySize: 512,
    logRetention: RetentionDays.ONE_MONTH,
    environment: commonEnv,
  });
  props.table.grantReadWriteData(ingestFn);
  props.eventStream.grantWrite(ingestFn);
  ingestFn.addToRolePolicy(telegramSsmPolicy());

  // Wire API Gateway route (no authorizer — Telegram calls this)
  // POST /webhooks/telegram/{token_hash}
  // Reuse or create the 'webhooks' resource if it already exists
  let webhooksResource = props.api.root.getResource('webhooks');
  if (!webhooksResource) {
    webhooksResource = props.api.root.addResource('webhooks');
  }
  let telegramResource = webhooksResource.getResource('telegram');
  if (!telegramResource) {
    telegramResource = webhooksResource.addResource('telegram');
  }
  const tokenHashResource = telegramResource.addResource('{token_hash}');
  tokenHashResource.addMethod('POST', new LambdaIntegration(ingestFn), {
    authorizationType: AuthorizationType.NONE,
  });

  return { ingestFn };
}

// ── TelegramAdapterStack: outbound queue + worker ─────────────────────────────
//
// Creates the SQS outbound queue and the outbound Lambda consumer.
// The inbound API GW route is NOT in this stack — it's wired by
// addTelegramAdapter() into the existing AgentCommsApiStack.
//
export class TelegramAdapterStack extends Stack {
  public readonly outboundFunction: LambdaFn;
  public readonly outboundQueue: Queue;
  public readonly outboundDlq: Queue;

  constructor(scope: Construct, id: string, props: TelegramAdapterStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '../../..');
    const code = makeLambdaCode(repoRoot);

    const commonEnv = {
      AGENTCOMMS_TABLE: props.table.tableName,
      AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      AGENTCOMMS_ENV: 'prod',
    };

    // ── Outbound SQS + Lambda ──
    // Dead-letter queue captures messages that fail 5 delivery attempts.
    this.outboundDlq = new Queue(this, 'TelegramOutboundDLQ', {
      queueName: 'agentcomms-telegram-outbound-dlq',
      retentionPeriod: Duration.days(14),
    });
    this.outboundQueue = new Queue(this, 'TelegramOutboundQueue', {
      queueName: 'agentcomms-telegram-outbound',
      visibilityTimeout: Duration.seconds(60),
      deadLetterQueue: { queue: this.outboundDlq, maxReceiveCount: 5 },
    });
    // Alarm when any message lands in the DLQ (outbound send failing repeatedly).
    this.outboundDlq
      .metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(5), statistic: 'Maximum' })
      .createAlarm(this, 'TelegramOutboundDLQAlarm', {
        alarmName: 'agentcomms-telegram-outbound-dlq-not-empty',
        alarmDescription: 'agentcomms-telegram-outbound DLQ has messages — outbound Telegram delivery is failing.',
        threshold: 0,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });

    this.outboundFunction = new LambdaFn(this, 'TelegramOutboundFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.telegram.outbound.handler',
      code,
      timeout: Duration.seconds(30),
      memorySize: 512,
      logRetention: RetentionDays.ONE_MONTH,
      environment: commonEnv,
    });
    this.outboundFunction.addEventSource(new SqsEventSource(this.outboundQueue));
    props.table.grantReadWriteData(this.outboundFunction);
    props.eventStream.grantWrite(this.outboundFunction);
    this.outboundFunction.addToRolePolicy(telegramSsmPolicy());
  }
}
