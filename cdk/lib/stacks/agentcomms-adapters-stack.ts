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

export interface AgentCommsAdaptersStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
  rawInboundBucket: Bucket;
  bodiesBucket: Bucket;
  attachmentsBucket: Bucket;
  /** Phase 2: enable SMS adapter stack (default false until Phase 2 deploy). */
  enableSms?: boolean;
}

export class AgentCommsAdaptersStack extends Stack {
  public readonly emailAdapterStack: EmailAdapterStack;
  public readonly smsAdapterStack?: SmsAdapterStack;

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

    // ── Phase 2 (future) — Push adapter ──
    // new PushAdapterStack(scope, `${id}-Push`, { env: props.env, ...props });

    // ── Phase 3 (future) — Slack adapter ──
    // new SlackAdapterStack(scope, `${id}-Slack`, { env: props.env, ...props });

    // ── Phase 3 (future) — Telegram adapter ──
    // new TelegramAdapterStack(scope, `${id}-Telegram`, { env: props.env, ...props });
  }
}
