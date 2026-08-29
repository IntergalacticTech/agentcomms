// cdk/test/agentcomms-data-stack.test.ts
import { App } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { AgentCommsDataStack } from '../lib/stacks/agentcomms-data-stack';

describe('AgentCommsDataStack', () => {
  const app = new App();
  const stack = new AgentCommsDataStack(app, 'Test');
  const template = Template.fromStack(stack);

  test('creates DynamoDB table named agentcomms with PAY_PER_REQUEST', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'agentcomms',
      BillingMode: 'PAY_PER_REQUEST',
    });
  });

  test('has 7 GSIs named GSI1..GSI7', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({ IndexName: 'GSI1' }),
        Match.objectLike({ IndexName: 'GSI7' }),
      ]),
    });
    const tables = template.findResources('AWS::DynamoDB::Table');
    const table = Object.values(tables)[0] as any;
    expect(table.Properties.GlobalSecondaryIndexes).toHaveLength(7);
  });

  test('creates 3 S3 buckets with agentcomms prefix', () => {
    template.resourceCountIs('AWS::S3::Bucket', 3);
    // BucketName is a Fn::Join token because this.account is a CDK token —
    // verify the raw-inbound bucket exists by checking for its lifecycle rule
    // and that the join prefix starts with 'agentcomms-raw-inbound'
    const buckets = template.findResources('AWS::S3::Bucket');
    const bucketValues = Object.values(buckets) as any[];
    const rawInbound = bucketValues.find((b: any) => {
      const name = b.Properties?.BucketName;
      // The bucket name is a Fn::Join: ["", ["agentcomms-raw-inbound-prod-", {"Ref": "AWS::AccountId"}]]
      return (
        name?.['Fn::Join'] &&
        Array.isArray(name['Fn::Join'][1]) &&
        name['Fn::Join'][1].some(
          (part: any) => typeof part === 'string' && part.startsWith('agentcomms-raw-inbound')
        )
      );
    });
    expect(rawInbound).toBeDefined();
  });

  test('DynamoDB point-in-time recovery enabled', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
    });
  });
});
