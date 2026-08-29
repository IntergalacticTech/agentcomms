// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.

// cdk/lib/adapters/sms-adapter-stack.ts
//
// SMS adapter AWS resources:
//   - SNS topic 'agentcomms-sms-inbound' that the ingest Lambda subscribes to.
//     Operator setup: configure End User Messaging to publish inbound SMS events
//     to this topic (set the phone number's SNS destination in the AWS console
//     or via CLI after provisioning).
//   - Lambda subscribed to SNS topic → adapters/sms/ingest.py handler
//   - SQS queue for outbound sends → adapters/sms/outbound.py Lambda consumer
//   - IAM grants: sms-voice:SendTextMessage, sms-voice:DescribePhoneNumbers,
//     sms-voice:RequestPhoneNumber, sms-voice:ReleasePhoneNumber
//
import * as path from 'path';
import { execSync } from 'child_process';
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Function as LambdaFn, Runtime, Code } from 'aws-cdk-lib/aws-lambda';
import { RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { SqsEventSource, SnsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Stream } from 'aws-cdk-lib/aws-kinesis';
import { ComparisonOperator, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';

export interface SmsAdapterStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
}

export class SmsAdapterStack extends Stack {
  public readonly ingestFunction: LambdaFn;
  public readonly outboundFunction: LambdaFn;
  public readonly outboundQueue: Queue;
  public readonly outboundDlq: Queue;
  public readonly inboundTopic: Topic;

  constructor(scope: Construct, id: string, props: SmsAdapterStackProps) {
    super(scope, id, props);

    // ── Shared local bundler ──
    const repoRoot = path.resolve(__dirname, '../../..');
    const makeLambdaCode = () => Code.fromAsset(repoRoot, {
      exclude: [
        'cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '.venv',
        '__pycache__', '*.pyc', '*.md', '.claude', '.github',
      ],
      bundling: {
        image: Runtime.PYTHON_3_12.bundlingImage,
        local: {
          tryBundle(outputDir: string): boolean {
            try {
              const tmpStage = `/tmp/agentcomms-sms-lambda-bundle-${Date.now()}`;
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

    // ── Inbound SNS topic ──
    // End User Messaging (10DLC phone) must be configured to publish inbound
    // SMS events to this topic. This is done in the AWS console or CLI after
    // the phone number is provisioned (operator step, not automated here).
    this.inboundTopic = new Topic(this, 'SmsInboundTopic', {
      topicName: 'agentcomms-sms-inbound',
    });

    // ── Ingest Lambda ──
    this.ingestFunction = new LambdaFn(this, 'SmsIngestFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.sms.ingest.handler',
      code: makeLambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 512,
      logRetention: RetentionDays.ONE_MONTH,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      },
    });
    this.ingestFunction.addEventSource(new SnsEventSource(this.inboundTopic));
    props.table.grantReadWriteData(this.ingestFunction);
    props.eventStream.grantWrite(this.ingestFunction);

    // ── Outbound SQS + Lambda ──
    // Dead-letter queue captures messages that fail 5 delivery attempts.
    this.outboundDlq = new Queue(this, 'SmsOutboundDLQ', {
      queueName: 'agentcomms-sms-outbound-dlq',
      retentionPeriod: Duration.days(14),
    });
    this.outboundQueue = new Queue(this, 'SmsOutboundQueue', {
      queueName: 'agentcomms-sms-outbound',
      visibilityTimeout: Duration.seconds(60),
      deadLetterQueue: { queue: this.outboundDlq, maxReceiveCount: 5 },
    });
    // Alarm when any message lands in the DLQ (outbound send failing repeatedly).
    this.outboundDlq
      .metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(5), statistic: 'Maximum' })
      .createAlarm(this, 'SmsOutboundDLQAlarm', {
        alarmName: 'agentcomms-sms-outbound-dlq-not-empty',
        alarmDescription: 'agentcomms-sms-outbound DLQ has messages — outbound SMS delivery is failing.',
        threshold: 0,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });
    this.outboundFunction = new LambdaFn(this, 'SmsOutboundFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.sms.outbound.handler',
      code: makeLambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 512,
      logRetention: RetentionDays.ONE_MONTH,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      },
    });
    this.outboundFunction.addEventSource(new SqsEventSource(this.outboundQueue));
    props.table.grantReadWriteData(this.outboundFunction);
    props.eventStream.grantWrite(this.outboundFunction);

    // ── IAM: End User Messaging permissions ──
    // Ingest Lambda only needs describe (to verify numbers if needed)
    this.ingestFunction.addToRolePolicy(new PolicyStatement({
      actions: ['sms-voice:DescribePhoneNumbers'],
      resources: ['*'],
    }));

    // Outbound Lambda needs send + describe
    this.outboundFunction.addToRolePolicy(new PolicyStatement({
      actions: [
        'sms-voice:SendTextMessage',
        'sms-voice:DescribePhoneNumbers',
      ],
      resources: ['*'],
    }));

    // Provisioning is done via the core API Lambda (not these workers), but
    // we export a shared policy statement for it. Uncomment in api-stack when
    // SMS provisioning is wired into the API handler.
    //
    // coreApiFunction.addToRolePolicy(new PolicyStatement({
    //   actions: [
    //     'sms-voice:RequestPhoneNumber',
    //     'sms-voice:ReleasePhoneNumber',
    //     'sms-voice:DescribePhoneNumbers',
    //   ],
    //   resources: ['*'],
    // }));
  }
}
