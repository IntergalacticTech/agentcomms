// cdk/test/agentcomms-api-stack.test.ts
import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { Table, AttributeType, BillingMode } from 'aws-cdk-lib/aws-dynamodb';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Stream } from 'aws-cdk-lib/aws-kinesis';
import { AgentCommsApiStack } from '../lib/stacks/agentcomms-api-stack';

function buildStack() {
  const app = new App();
  // Dependency stubs
  const depStack = new Stack(app, 'Deps');
  const table = new Table(depStack, 'Table', {
    partitionKey: { name: 'PK', type: AttributeType.STRING },
    sortKey:      { name: 'SK', type: AttributeType.STRING },
    billingMode:  BillingMode.PAY_PER_REQUEST,
  });
  const rawInboundBucket   = new Bucket(depStack, 'RawInbound');
  const bodiesBucket       = new Bucket(depStack, 'Bodies');
  const attachmentsBucket  = new Bucket(depStack, 'Attachments');
  const eventStream        = new Stream(depStack, 'Events');

  const stack = new AgentCommsApiStack(app, 'ApiTest', {
    table,
    eventStream,
    rawInboundBucket,
    bodiesBucket,
    attachmentsBucket,
  });
  return Template.fromStack(stack);
}

describe('AgentCommsApiStack', () => {
  const template = buildStack();

  test('creates a RestApi named agentcomms-api', () => {
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      Name: 'agentcomms-api',
    });
  });

  test('has a TOKEN Lambda authorizer', () => {
    template.hasResourceProperties('AWS::ApiGateway::Authorizer', {
      Type: 'TOKEN',
    });
  });

  test('has at least 9 Lambda functions (8 handlers + 1 authorizer)', () => {
    const lambdas = template.findResources('AWS::Lambda::Function');
    expect(Object.keys(lambdas).length).toBeGreaterThanOrEqual(9);
  });

  test('has at least 20 API Gateway methods', () => {
    const methods = template.findResources('AWS::ApiGateway::Method');
    // exclude OPTIONS / ANY if any; just ensure count ≥ 20
    expect(Object.keys(methods).length).toBeGreaterThanOrEqual(20);
  });
});
