// cdk/test/agentcomms-events-stack.test.ts
import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { AgentCommsEventsStack } from '../lib/stacks/agentcomms-events-stack';

describe('AgentCommsEventsStack', () => {
  const app = new App();
  const stack = new AgentCommsEventsStack(app, 'Test');
  const tpl = Template.fromStack(stack);

  test('Kinesis stream with 4 shards', () => {
    tpl.hasResourceProperties('AWS::Kinesis::Stream', {
      Name: 'agentcomms-events',
      ShardCount: 4,
      RetentionPeriodHours: 168,  // 7 days
    });
  });
});
