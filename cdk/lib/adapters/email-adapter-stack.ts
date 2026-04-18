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
}

export class EmailAdapterStack extends Stack {
  public readonly ingestFunction: LambdaFn;
  public readonly outboundFunction: LambdaFn;
  public readonly outboundQueue: Queue;

  constructor(scope: Construct, id: string, props: EmailAdapterStackProps) {
    super(scope, id, props);

    // SNS topic SES publishes to
    const inboundTopic = new Topic(this, 'EmailInboundTopic', {
      topicName: 'agentcomms-email-inbound',
    });

    // Ingest Lambda
    this.ingestFunction = new LambdaFn(this, 'EmailIngestFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.email.ingest.handler',
      code: Code.fromAsset('..', {
        exclude: ['cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '*.md'],
      }),
      timeout: Duration.seconds(30),
      memorySize: 1024,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_BUCKET_RAW_INBOUND: props.rawInboundBucket.bucketName,
        AGENTCOMMS_BUCKET_BODIES: props.bodiesBucket.bucketName,
        AGENTCOMMS_BUCKET_ATTACHMENTS: props.attachmentsBucket.bucketName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
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
      code: Code.fromAsset('..', {
        exclude: ['cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '*.md'],
      }),
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
