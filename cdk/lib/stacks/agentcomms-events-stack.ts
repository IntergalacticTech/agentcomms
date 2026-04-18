// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

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
