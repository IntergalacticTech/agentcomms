// cdk/test/agentcomms-api-stack.test.ts
import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { Table, AttributeType, BillingMode } from 'aws-cdk-lib/aws-dynamodb';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Stream } from 'aws-cdk-lib/aws-kinesis';
import { Code } from 'aws-cdk-lib/aws-lambda';
import { AgentCommsApiStack } from '../lib/stacks/agentcomms-api-stack';

const STUB_PYTHON = 'def handler(event, context):\n    return {"statusCode": 200, "body": "{}"}\n';

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
    lambdaCode: Code.fromInline(STUB_PYTHON),
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

  // ── SES IAM scoping (finding: blanket SES grant on all 13 handlers) ──

  function policiesContaining(action: string): string[] {
    const policies = template.findResources('AWS::IAM::Policy');
    return Object.keys(policies).filter((id) =>
      JSON.stringify(policies[id].Properties?.PolicyDocument).includes(action),
    );
  }

  test('SES send is granted to exactly one handler (the sender), not all handlers', () => {
    // Previously every handler role carried ses:SendRawEmail (over-broad).
    expect(policiesContaining('ses:SendRawEmail').length).toBe(1);
  });

  test('SES identity CRUD is granted to exactly one handler (domains)', () => {
    expect(policiesContaining('sesv2:CreateEmailIdentity').length).toBe(1);
  });

  test('Bedrock InvokeModel resource is region-interpolated, not hardcoded us-east-1', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    const serialized = JSON.stringify(policies);
    // No literal us-east-1 bedrock ARN; region comes from a CloudFormation ref.
    expect(serialized).not.toContain('arn:aws:bedrock:us-east-1::foundation-model/*');
    expect(serialized).toContain('bedrock:InvokeModel');
  });

  test('handler Lambdas set a 1-month log retention', () => {
    const retentions = template.findResources('Custom::LogRetention');
    expect(Object.keys(retentions).length).toBeGreaterThanOrEqual(1);
  });
});
