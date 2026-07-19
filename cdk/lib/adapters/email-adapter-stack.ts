// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

// cdk/lib/adapters/email-adapter-stack.ts
//
// Email adapter AWS resources:
//   - SES receipt rule set that captures inbound mail for the configured domains
//   - S3 action → agentcomms-raw-inbound bucket
//   - SNS action → AgentComms email-ingest topic
//   - Lambda subscribed to SNS topic → adapters/email/ingest.py handler
//   - SQS queue for outbound sends → adapters/email/outbound.py Lambda consumer
//   - SES configuration set for outbound bounces/complaints
//
// NOTE: The Python adapter's cdk_wiring() method in manifest.toml is a no-op for the
// email adapter — its AWS resources are declared here in TypeScript CDK instead.
// This stack is instantiated in Task 26's adapters orchestration stack.
//
import * as path from 'path';
import { execSync } from 'child_process';
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Function as LambdaFn, Runtime, Code } from 'aws-cdk-lib/aws-lambda';
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { SqsEventSource, SnsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { ReceiptRuleSet } from 'aws-cdk-lib/aws-ses';
import { S3, Sns } from 'aws-cdk-lib/aws-ses-actions';
import { Stream } from 'aws-cdk-lib/aws-kinesis';

export interface EmailAdapterStackProps extends StackProps {
  table: Table;
  rawInboundBucket: Bucket;
  bodiesBucket: Bucket;
  attachmentsBucket: Bucket;
  eventStream: Stream;
  inboundDomains: string[];    // e.g. ['agentcomms.dev']
  /** Optional Lambda code override for fast template tests. Production uses bundled repo assets. */
  lambdaCode?: Code;
}

export class EmailAdapterStack extends Stack {
  public readonly ingestFunction: LambdaFn;
  public readonly outboundFunction: LambdaFn;
  public readonly outboundQueue: Queue;

  constructor(scope: Construct, id: string, props: EmailAdapterStackProps) {
    super(scope, id, props);

    // ── Shared local bundler ──
    // Avoids mounting the large repo root into Docker (hits fd limits).
    const repoRoot = path.resolve(__dirname, '../../..');
    const makeLambdaCode = () => props.lambdaCode ?? Code.fromAsset(repoRoot, {
      exclude: [
        'cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '.venv',
        '__pycache__', '*.pyc', '*.md', '.claude', '.github',
      ],
      bundling: {
        image: Runtime.PYTHON_3_12.bundlingImage,
        local: {
          tryBundle(outputDir: string): boolean {
            try {
              // Stage everything under /tmp to avoid Docker Desktop fd-limit when
              // mounting /Users paths. pydantic_core is a Rust extension that must
              // be built for linux/amd64 to work in Lambda.
              const tmpStage = `/tmp/agentcomms-lambda-bundle-${Date.now()}`;
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
              // Copy the staged output into the CDK output directory
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

    // SNS topic SES publishes to
    const inboundTopic = new Topic(this, 'EmailInboundTopic', {
      topicName: 'agentcomms-email-inbound',
    });

    // Ingest Lambda
    this.ingestFunction = new LambdaFn(this, 'EmailIngestFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.email.ingest.handler',
      code: makeLambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 1024,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_BUCKET_RAW_INBOUND: props.rawInboundBucket.bucketName,
        AGENTCOMMS_BUCKET_BODIES: props.bodiesBucket.bucketName,
        AGENTCOMMS_BUCKET_ATTACHMENTS: props.attachmentsBucket.bucketName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
        AGENTCOMMS_RAW_INBOUND_PREFIX: 'inbound/',
      },
    });
    this.ingestFunction.addEventSource(new SnsEventSource(inboundTopic));
    props.table.grantReadWriteData(this.ingestFunction);
    props.rawInboundBucket.grantRead(this.ingestFunction);
    props.eventStream.grantWrite(this.ingestFunction);

    // SES receipt rule
    const ruleSet = new ReceiptRuleSet(this, 'EmailReceipt', { receiptRuleSetName: 'agentcomms' });
    ruleSet.addRule('CatchAll', {
      recipients: props.inboundDomains,
      actions: [
        new S3({ bucket: props.rawInboundBucket, objectKeyPrefix: 'inbound/' }),
        new Sns({ topic: inboundTopic }),
      ],
    });

    // Outbound
    this.outboundQueue = new Queue(this, 'EmailOutboundQueue', {
      queueName: 'agentcomms-email-outbound',
      visibilityTimeout: Duration.seconds(60),
    });
    this.outboundFunction = new LambdaFn(this, 'EmailOutboundFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.email.outbound.handler',
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
    this.outboundFunction.addToRolePolicy(
      // SES send permission (scoped in real deploy; wildcard here for brevity)
      new (require('aws-cdk-lib/aws-iam').PolicyStatement)({
        actions: ['ses:SendRawEmail'],
        resources: ['*'],
      }),
    );
    props.eventStream.grantWrite(this.outboundFunction);
  }
}
