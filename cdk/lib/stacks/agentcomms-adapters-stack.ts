// cdk/lib/stacks/agentcomms-adapters-stack.ts
//
// Adapters orchestration stack — thin wrapper that instantiates every channel
// adapter sub-stack and wires them to the shared data/events resources.
//
// Phase 1: Email adapter only.
//
// Future phases will add adapters here as they land:
//   Phase 2 — SMS (Twilio/SNS), Push (APNs/FCM via SNS)
//   Phase 3 — Slack, Telegram
//
// Long-term design intent: scan adapters/*/manifest.toml at CDK synth time,
// dynamically load each adapter's `cdk_stack` reference (per the ChannelAdapter
// contract), and instantiate it with these props.  Phase 1 scope is explicit
// email-only instantiation — defer dynamic discovery until ≥2 adapters exist.
//
import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Stream } from 'aws-cdk-lib/aws-kinesis';
import { EmailAdapterStack } from '../adapters/email-adapter-stack';
import { SmsAdapterStack } from '../adapters/sms-adapter-stack';
import { PushAdapterStack } from '../adapters/push-adapter-stack';
import { SlackAdapterStack } from '../adapters/slack-adapter-stack';
import { TelegramAdapterStack } from '../adapters/telegram-adapter-stack';

export interface AgentCommsAdaptersStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
  rawInboundBucket: Bucket;
  bodiesBucket: Bucket;
  attachmentsBucket: Bucket;
  /** Phase 2: enable SMS adapter stack (default false until Phase 2 deploy). */
  enableSms?: boolean;
  /** Phase 2: enable Push adapter stack (default false until Phase 2 deploy). */
  enablePush?: boolean;
  /** Phase 3: enable Slack adapter stack (default false until Phase 3 deploy). */
  enableSlack?: boolean;
  /** Phase 3: enable Telegram adapter stack (default false until Phase 3 deploy). */
  enableTelegram?: boolean;
}

export class AgentCommsAdaptersStack extends Stack {
  public readonly emailAdapterStack: EmailAdapterStack;
  public readonly smsAdapterStack?: SmsAdapterStack;
  public readonly pushAdapterStack?: PushAdapterStack;
  public readonly slackAdapterStack?: SlackAdapterStack;
  public readonly telegramAdapterStack?: TelegramAdapterStack;

  constructor(scope: Construct, id: string, props: AgentCommsAdaptersStackProps) {
    super(scope, id, props);

    // ── Phase 1: Email adapter ──
    this.emailAdapterStack = new EmailAdapterStack(scope, `${id}-Email`, {
      env: props.env,
      table: props.table,
      rawInboundBucket: props.rawInboundBucket,
      bodiesBucket: props.bodiesBucket,
      attachmentsBucket: props.attachmentsBucket,
      eventStream: props.eventStream,
      inboundDomains: ['agentcomms.dev'],
    });

    // ── Phase 2: SMS adapter (disabled by default; enable via enableSms: true) ──
    if (props.enableSms) {
      this.smsAdapterStack = new SmsAdapterStack(scope, `${id}-Sms`, {
        env: props.env,
        table: props.table,
        eventStream: props.eventStream,
      });
    }

    // ── Phase 2: Push adapter (disabled by default; enable via enablePush: true) ──
    if (props.enablePush) {
      this.pushAdapterStack = new PushAdapterStack(scope, `${id}-Push`, {
        env: props.env,
        table: props.table,
        eventStream: props.eventStream,
      });
    }

    // ── Phase 3: Slack adapter (disabled by default; enable via enableSlack: true) ──
    if (props.enableSlack) {
      this.slackAdapterStack = new SlackAdapterStack(scope, `${id}-Slack`, {
        env: props.env,
        table: props.table,
        eventStream: props.eventStream,
      });
    }

    // ── Phase 3: Telegram adapter (disabled by default; enable via enableTelegram: true) ──
    if (props.enableTelegram) {
      this.telegramAdapterStack = new TelegramAdapterStack(scope, `${id}-Telegram`, {
        env: props.env,
        table: props.table,
        eventStream: props.eventStream,
      });
    }
  }
}
