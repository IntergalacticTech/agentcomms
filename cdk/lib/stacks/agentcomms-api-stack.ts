// cdk/lib/stacks/agentcomms-api-stack.ts
//
// AgentComms REST API:
//   - API Gateway RestApi named 'agentcomms-api'
//   - TOKEN Lambda authorizer wrapping core/api/authorizer_lambda.py
//   - 8 handler Lambdas (agents, channels, messages, threads, drafts, webhooks, wait, otp)
//   - Routes wired under /v1/agents/*
//
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Stream } from 'aws-cdk-lib/aws-kinesis';
import {
  Function as LambdaFn, Runtime, Code,
} from 'aws-cdk-lib/aws-lambda';
import {
  RestApi, LambdaIntegration, TokenAuthorizer, AuthorizationType,
  MethodOptions,
} from 'aws-cdk-lib/aws-apigateway';
import { PolicyStatement, Effect } from 'aws-cdk-lib/aws-iam';

export interface AgentCommsApiStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
  rawInboundBucket: Bucket;
  bodiesBucket: Bucket;
  attachmentsBucket: Bucket;
}

export class AgentCommsApiStack extends Stack {
  public readonly api: RestApi;

  constructor(scope: Construct, id: string, props: AgentCommsApiStackProps) {
    super(scope, id, props);

    // ── Common asset packaging (same exclusion list as email adapter) ──
    const lambdaCode = () => Code.fromAsset('..', {
      exclude: ['cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '*.md'],
    });

    // ── Common env vars for all handler Lambdas ──
    const commonEnv = {
      AGENTCOMMS_TABLE: props.table.tableName,
      AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
    };

    // ── Lambda Authorizer ──
    const authorizerFn = new LambdaFn(this, 'AuthorizerFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'core.api.authorizer_lambda.lambda_handler',
      code: lambdaCode(),
      timeout: Duration.seconds(10),
      memorySize: 256,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
      },
    });
    // Authorizer needs GSI1 read (API key lookup)
    props.table.grantReadData(authorizerFn);

    const authorizer = new TokenAuthorizer(this, 'ApiAuthorizer', {
      handler: authorizerFn,
      identitySource: 'method.request.header.Authorization',
      resultsCacheTtl: Duration.seconds(300),
    });

    const authMethodOptions: MethodOptions = {
      authorizer,
      authorizationType: AuthorizationType.CUSTOM,
    };

    // ── Helper: create a handler Lambda with optional Kinesis write grant ──
    const makeHandlerFn = (
      id: string,
      handlerModule: string,
      grantKinesisWrite: boolean = false,
    ): LambdaFn => {
      const fn = new LambdaFn(this, id, {
        runtime: Runtime.PYTHON_3_12,
        handler: `core.api.${handlerModule}.handler`,
        code: lambdaCode(),
        timeout: Duration.seconds(30),
        memorySize: 512,
        environment: commonEnv,
      });
      props.table.grantReadWriteData(fn);
      if (grantKinesisWrite) {
        props.eventStream.grantWrite(fn);
      }
      return fn;
    };

    // ── 8 Handler Lambdas ──
    // agents, channels, messages publish events → grant Kinesis write
    const agentsFn    = makeHandlerFn('AgentsFn',    'agents_handler',    true);
    const channelsFn  = makeHandlerFn('ChannelsFn',  'channels_handler',  true);
    const messagesFn  = makeHandlerFn('MessagesFn',  'messages_handler',  true);
    const threadsFn   = makeHandlerFn('ThreadsFn',   'threads_handler',   false);
    const draftsFn    = makeHandlerFn('DraftsFn',    'drafts_handler',    false);
    const webhooksFn  = makeHandlerFn('WebhooksFn',  'webhooks_handler',  false);
    const waitFn      = makeHandlerFn('WaitFn',      'wait_handler',      false);
    const otpFn       = makeHandlerFn('OtpFn',       'otp_handler',       false);

    // ── REST API ──
    this.api = new RestApi(this, 'AgentCommsApi', {
      restApiName: 'agentcomms-api',
      description: 'AgentComms hub REST API',
      deployOptions: { stageName: 'prod' },
    });

    // ── Route wiring ──
    const v1 = this.api.root.addResource('v1');
    const agents = v1.addResource('agents');

    // /v1/agents  →  GET, POST
    agents.addMethod('GET',  new LambdaIntegration(agentsFn), authMethodOptions);
    agents.addMethod('POST', new LambdaIntegration(agentsFn), authMethodOptions);

    // /v1/agents/{agent_id}
    const agent = agents.addResource('{agent_id}');
    agent.addMethod('GET',    new LambdaIntegration(agentsFn), authMethodOptions);
    agent.addMethod('PUT',    new LambdaIntegration(agentsFn), authMethodOptions);
    agent.addMethod('DELETE', new LambdaIntegration(agentsFn), authMethodOptions);

    // /v1/agents/{agent_id}/provision
    const provision = agent.addResource('provision');
    provision.addMethod('POST', new LambdaIntegration(agentsFn), authMethodOptions);

    // /v1/agents/{agent_id}/channels
    const channels = agent.addResource('channels');
    channels.addMethod('GET',  new LambdaIntegration(channelsFn), authMethodOptions);
    channels.addMethod('POST', new LambdaIntegration(channelsFn), authMethodOptions);

    // /v1/agents/{agent_id}/channels/{channel_id}
    const channel = channels.addResource('{channel_id}');
    channel.addMethod('GET',    new LambdaIntegration(channelsFn), authMethodOptions);
    channel.addMethod('PUT',    new LambdaIntegration(channelsFn), authMethodOptions);
    channel.addMethod('DELETE', new LambdaIntegration(channelsFn), authMethodOptions);

    // /v1/agents/{agent_id}/messages
    const messages = agent.addResource('messages');
    messages.addMethod('GET',  new LambdaIntegration(messagesFn), authMethodOptions);
    messages.addMethod('POST', new LambdaIntegration(messagesFn), authMethodOptions);

    // /v1/agents/{agent_id}/messages/{message_id}
    const message = messages.addResource('{message_id}');
    message.addMethod('GET',    new LambdaIntegration(messagesFn), authMethodOptions);
    message.addMethod('DELETE', new LambdaIntegration(messagesFn), authMethodOptions);

    // /v1/agents/{agent_id}/threads
    const threads = agent.addResource('threads');
    threads.addMethod('GET', new LambdaIntegration(threadsFn), authMethodOptions);

    // /v1/agents/{agent_id}/threads/{thread_id}
    const thread = threads.addResource('{thread_id}');
    thread.addMethod('GET', new LambdaIntegration(threadsFn), authMethodOptions);

    // /v1/agents/{agent_id}/drafts
    const drafts = agent.addResource('drafts');
    drafts.addMethod('GET',  new LambdaIntegration(draftsFn), authMethodOptions);
    drafts.addMethod('POST', new LambdaIntegration(draftsFn), authMethodOptions);

    // /v1/agents/{agent_id}/drafts/{draft_id}
    const draft = drafts.addResource('{draft_id}');
    draft.addMethod('GET',    new LambdaIntegration(draftsFn), authMethodOptions);
    draft.addMethod('PUT',    new LambdaIntegration(draftsFn), authMethodOptions);
    draft.addMethod('DELETE', new LambdaIntegration(draftsFn), authMethodOptions);

    // /v1/agents/{agent_id}/webhooks
    const webhooks = agent.addResource('webhooks');
    webhooks.addMethod('GET',  new LambdaIntegration(webhooksFn), authMethodOptions);
    webhooks.addMethod('POST', new LambdaIntegration(webhooksFn), authMethodOptions);

    // /v1/agents/{agent_id}/webhooks/{webhook_id}
    const webhook = webhooks.addResource('{webhook_id}');
    webhook.addMethod('GET',    new LambdaIntegration(webhooksFn), authMethodOptions);
    webhook.addMethod('PUT',    new LambdaIntegration(webhooksFn), authMethodOptions);
    webhook.addMethod('DELETE', new LambdaIntegration(webhooksFn), authMethodOptions);

    // /v1/agents/{agent_id}/wait
    const wait = agent.addResource('wait');
    wait.addMethod('POST', new LambdaIntegration(waitFn), authMethodOptions);

    // /v1/agents/{agent_id}/extract-otp
    const extractOtp = agent.addResource('extract-otp');
    extractOtp.addMethod('POST', new LambdaIntegration(otpFn), authMethodOptions);
  }
}
