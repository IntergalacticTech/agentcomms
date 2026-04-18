// cdk/lib/stacks/agentcomms-events-stack.ts
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Stream, StreamMode } from 'aws-cdk-lib/aws-kinesis';

export class AgentCommsEventsStack extends Stack {
  public readonly eventStream: Stream;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);
    this.eventStream = new Stream(this, 'AgentCommsEvents', {
      streamName: 'agentcomms-events',
      shardCount: 4,
      retentionPeriod: Duration.days(7),
      streamMode: StreamMode.PROVISIONED,
    });
  }
}
