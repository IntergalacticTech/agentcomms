// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

// cdk/lib/adapters/push-adapter-stack.ts
//
// Push adapter AWS resources (SNS Mobile Push — APNs + FCM):
//   - SNS topic 'agentcomms-push-delivery' for delivery receipts
//     Subscribed by the ingest Lambda; operator must configure SNS
//     Platform Application delivery-status logging to publish to this topic.
//   - Lambda subscribed to SNS topic → adapters/push/ingest.py handler
//   - SQS queue for outbound sends → adapters/push/outbound.py Lambda consumer
//   - IAM for:
//       sns:Publish
//       sns:CreatePlatformEndpoint
//       sns:DeleteEndpoint
//       sns:ListEndpointsByPlatformApplication
//       sns:GetPlatformApplicationAttributes
//       sns:CreatePlatformApplication
//
import * as path from 'path';
import { execSync } from 'child_process';
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Function as LambdaFn, Runtime, Code } from 'aws-cdk-lib/aws-lambda';
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { SqsEventSource, SnsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Stream } from 'aws-cdk-lib/aws-kinesis';

export interface PushAdapterStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
}

export class PushAdapterStack extends Stack {
  public readonly ingestFunction: LambdaFn;
  public readonly outboundFunction: LambdaFn;
  public readonly outboundQueue: Queue;
  public readonly deliveryTopic: Topic;

  constructor(scope: Construct, id: string, props: PushAdapterStackProps) {
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
              const tmpStage = `/tmp/agentcomms-push-lambda-bundle-${Date.now()}`;
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

    // ── Delivery receipt SNS topic ──
    // SNS Platform Application delivery-status logging must be configured to
    // publish to this topic. This is done in the AWS console or via CLI after
    // the platform application is provisioned (operator step).
    this.deliveryTopic = new Topic(this, 'PushDeliveryTopic', {
      topicName: 'agentcomms-push-delivery',
    });

    // ── Ingest Lambda (delivery receipts) ──
    this.ingestFunction = new LambdaFn(this, 'PushIngestFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.push.ingest.handler',
      code: makeLambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 512,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      },
    });
    this.ingestFunction.addEventSource(new SnsEventSource(this.deliveryTopic));
    props.table.grantReadWriteData(this.ingestFunction);
    props.eventStream.grantWrite(this.ingestFunction);

    // ── Outbound SQS + Lambda ──
    this.outboundQueue = new Queue(this, 'PushOutboundQueue', {
      queueName: 'agentcomms-push-outbound',
      visibilityTimeout: Duration.seconds(60),
    });
    this.outboundFunction = new LambdaFn(this, 'PushOutboundFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.push.outbound.handler',
      code: makeLambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 512,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      },
    });
    this.outboundFunction.addEventSource(new SqsEventSource(this.outboundQueue));
    props.table.grantReadWriteData(this.outboundFunction);
    props.eventStream.grantWrite(this.outboundFunction);

    // ── IAM: SNS Mobile Push permissions ──

    // Ingest Lambda: read-only SNS ops to verify endpoints
    this.ingestFunction.addToRolePolicy(new PolicyStatement({
      actions: [
        'sns:GetPlatformApplicationAttributes',
        'sns:ListEndpointsByPlatformApplication',
      ],
      resources: ['*'],
    }));

    // Outbound Lambda: publish to device endpoints
    this.outboundFunction.addToRolePolicy(new PolicyStatement({
      actions: [
        'sns:Publish',
        'sns:GetPlatformApplicationAttributes',
      ],
      resources: ['*'],
    }));

    // The core API Lambda (not defined here) needs these for device registration
    // and channel provisioning. Reference when wiring push_native_handler into api-stack:
    //
    // coreApiFunction.addToRolePolicy(new PolicyStatement({
    //   actions: [
    //     'sns:CreatePlatformApplication',
    //     'sns:CreatePlatformEndpoint',
    //     'sns:DeleteEndpoint',
    //     'sns:ListEndpointsByPlatformApplication',
    //     'sns:GetPlatformApplicationAttributes',
    //   ],
    //   resources: ['*'],
    // }));
  }
}
