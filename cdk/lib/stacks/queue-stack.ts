// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as sqs from "aws-cdk-lib/aws-sqs";

export interface QueueStackProps extends cdk.StackProps {
  stage: string;
}

export class QueueStack extends cdk.Stack {
  public readonly sendQueue: sqs.Queue;
  public readonly sendDlq: sqs.Queue;
  public readonly webhookQueue: sqs.Queue;
  public readonly webhookDlq: sqs.Queue;

  constructor(scope: Construct, id: string, props: QueueStackProps) {
    super(scope, id, props);

    // ── Send Queue (FIFO) ──────────────────────────────────────────────

    this.sendDlq = new sqs.Queue(this, "SendDLQ", {
      queueName: "victorymail-send-dlq.fifo",
      fifo: true,
      retentionPeriod: cdk.Duration.days(14),
    });

    this.sendQueue = new sqs.Queue(this, "SendQueue", {
      queueName: "victorymail-send-queue.fifo",
      fifo: true,
      contentBasedDeduplication: true,
      visibilityTimeout: cdk.Duration.seconds(120),
      deadLetterQueue: {
        queue: this.sendDlq,
        maxReceiveCount: 3,
      },
    });

    // ── Webhook Queue (Standard) ───────────────────────────────────────

    this.webhookDlq = new sqs.Queue(this, "WebhookDLQ", {
      queueName: "victorymail-webhook-dlq",
      retentionPeriod: cdk.Duration.days(14),
    });

    this.webhookQueue = new sqs.Queue(this, "WebhookQueue", {
      queueName: "victorymail-webhook-queue",
      visibilityTimeout: cdk.Duration.seconds(60),
      deadLetterQueue: {
        queue: this.webhookDlq,
        maxReceiveCount: 5,
      },
    });

    // ── Outputs ────────────────────────────────────────────────────────

    new cdk.CfnOutput(this, "SendQueueUrl", {
      value: this.sendQueue.queueUrl,
    });
    new cdk.CfnOutput(this, "SendQueueArn", {
      value: this.sendQueue.queueArn,
    });
    new cdk.CfnOutput(this, "WebhookQueueUrl", {
      value: this.webhookQueue.queueUrl,
    });
    new cdk.CfnOutput(this, "WebhookQueueArn", {
      value: this.webhookQueue.queueArn,
    });
  }
}
