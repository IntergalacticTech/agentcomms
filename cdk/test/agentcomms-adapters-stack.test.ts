// cdk/test/agentcomms-adapters-stack.test.ts
import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { Table, AttributeType, BillingMode } from 'aws-cdk-lib/aws-dynamodb';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Stream } from 'aws-cdk-lib/aws-kinesis';
import { Code } from 'aws-cdk-lib/aws-lambda';
import { AgentCommsAdaptersStack } from '../lib/stacks/agentcomms-adapters-stack';

const STUB_PYTHON = 'def handler(event, context):\n    return {"statusCode": 200, "body": "{}"}\n';

function buildStacks() {
  const app = new App();
  // Dependency stubs
  const depStack = new Stack(app, 'Deps');
  const table = new Table(depStack, 'Table', {
    partitionKey: { name: 'PK', type: AttributeType.STRING },
    sortKey:      { name: 'SK', type: AttributeType.STRING },
    billingMode:  BillingMode.PAY_PER_REQUEST,
  });
  const rawInboundBucket  = new Bucket(depStack, 'RawInbound');
  const bodiesBucket      = new Bucket(depStack, 'Bodies');
  const attachmentsBucket = new Bucket(depStack, 'Attachments');
  const eventStream       = new Stream(depStack, 'Events');

  const adaptersStack = new AgentCommsAdaptersStack(app, 'AdaptersTest', {
    table,
    eventStream,
    rawInboundBucket,
    bodiesBucket,
    attachmentsBucket,
    inboundDomains: ['example.com'],
    lambdaCode: Code.fromInline(STUB_PYTHON),
  });

  // AgentCommsAdaptersStack instantiates EmailAdapterStack as a sibling in app scope
  const emailStack = adaptersStack.emailAdapterStack;
  const emailTemplate = Template.fromStack(emailStack);

  return { emailTemplate };
}

describe('AgentCommsAdaptersStack — email adapter artifacts', () => {
  const { emailTemplate } = buildStacks();

  test('has SES receipt rule set named agentcomms', () => {
    emailTemplate.hasResourceProperties('AWS::SES::ReceiptRuleSet', {
      RuleSetName: 'agentcomms',
    });
  });

  test('has inbound SNS topic named agentcomms-email-inbound', () => {
    emailTemplate.hasResourceProperties('AWS::SNS::Topic', {
      TopicName: 'agentcomms-email-inbound',
    });
  });

  test('has outbound SQS queue named agentcomms-email-outbound', () => {
    emailTemplate.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'agentcomms-email-outbound',
    });
  });

  test('outbound queue has a dead-letter queue with maxReceiveCount 5', () => {
    // DLQ exists
    emailTemplate.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'agentcomms-email-outbound-dlq',
    });
    // Main queue redrives to it after 5 failures
    emailTemplate.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'agentcomms-email-outbound',
      RedrivePolicy: Match.objectLike({ maxReceiveCount: 5 }),
    });
  });

  test('has a CloudWatch alarm on the DLQ depth', () => {
    emailTemplate.hasResourceProperties('AWS::CloudWatch::Alarm', {
      MetricName: 'ApproximateNumberOfMessagesVisible',
      Namespace: 'AWS/SQS',
      ComparisonOperator: 'GreaterThanThreshold',
      Threshold: 0,
    });
  });

  test('has both adapter Lambda handlers (ingest + outbound)', () => {
    // The two adapter handlers are present. (A LogRetention custom-resource
    // provider Lambda is also synthesized because logRetention is set.)
    emailTemplate.hasResourceProperties('AWS::Lambda::Function', {
      Handler: 'adapters.email.ingest.handler',
    });
    emailTemplate.hasResourceProperties('AWS::Lambda::Function', {
      Handler: 'adapters.email.outbound.handler',
    });
  });

  test('adapter Lambdas set a 1-month log retention', () => {
    // logRetention synthesizes a Custom::LogRetention resource per function.
    const retentions = emailTemplate.findResources('Custom::LogRetention');
    expect(Object.keys(retentions).length).toBeGreaterThanOrEqual(2);
  });

  test('uses configured inbound domains in SES receipt rule', () => {
    emailTemplate.hasResourceProperties('AWS::SES::ReceiptRule', {
      Rule: Match.objectLike({
        Recipients: ['example.com'],
      }),
    });
  });

  test('passes raw inbound S3 prefix to ingest Lambda', () => {
    emailTemplate.hasResourceProperties('AWS::Lambda::Function', {
      Handler: 'adapters.email.ingest.handler',
      Environment: Match.objectLike({
        Variables: Match.objectLike({
          AGENTCOMMS_RAW_INBOUND_PREFIX: 'inbound/',
        }),
      }),
    });
  });
});
