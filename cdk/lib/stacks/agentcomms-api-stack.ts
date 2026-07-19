// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

// cdk/lib/stacks/agentcomms-api-stack.ts
//
// AgentComms REST API:
//   - API Gateway RestApi named 'agentcomms-api'
//   - TOKEN Lambda authorizer wrapping core/api/authorizer_lambda.py
//   - 13 handler Lambdas (agents, channels, messages, threads, drafts, webhooks, wait, otp,
//                         vault, personas, domains, ai, push_native)
//   - Routes wired under /v1/agents/*, /v1/vault/*, /v1/personas/*, /v1/domains/*
//
import * as path from 'path';
import { execSync } from 'child_process';
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
import { Key } from 'aws-cdk-lib/aws-kms';
import { addSlackAdapter } from '../adapters/slack-adapter-stack';
import { addTelegramAdapter } from '../adapters/telegram-adapter-stack';

export interface AgentCommsApiStackProps extends StackProps {
  table: Table;
  eventStream: Stream;
  rawInboundBucket: Bucket;
  bodiesBucket: Bucket;
  attachmentsBucket: Bucket;
  /** Optional Lambda code override for fast template tests. Production uses bundled repo assets. */
  lambdaCode?: Code;
  /** Phase 3: enable Slack webhook routes (default false). */
  enableSlack?: boolean;
  /** Phase 3: enable Telegram webhook route (default false). */
  enableTelegram?: boolean;
}

export class AgentCommsApiStack extends Stack {
  public readonly api: RestApi;

  constructor(scope: Construct, id: string, props: AgentCommsApiStackProps) {
    super(scope, id, props);

    // ── Common asset packaging ──
    // Uses a local bundler (no Docker) to avoid mounting the large repo root
    // into a container and hitting file-descriptor limits. The local bundler
    // copies only core/ + adapters/ then installs pip deps natively.
    const repoRoot = path.resolve(__dirname, '../../..');
    const lambdaCode = () => props.lambdaCode ?? Code.fromAsset(repoRoot, {
      exclude: [
        'cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '.venv',
        '__pycache__', '*.pyc', '*.md', '.claude', '.github',
      ],
      bundling: {
        image: Runtime.PYTHON_3_12.bundlingImage,
        local: {
          tryBundle(outputDir: string): boolean {
            try {
              // Stage everything under /tmp to avoid Docker Desktop fd-limit when
              // mounting /Users paths. pydantic_core is a Rust extension that must
              // be built for linux/amd64 to work in Lambda.
              const tmpStage = `/tmp/agentcomms-lambda-bundle-${Date.now()}`;
              execSync(`mkdir -p ${tmpStage}`);
              execSync(`cp -r ${repoRoot}/core ${tmpStage}/`);
              execSync(`cp -r ${repoRoot}/adapters ${tmpStage}/`);
              execSync(`cp ${repoRoot}/requirements-lambda.txt ${tmpStage}/`);
              execSync(
                `docker run --rm --platform linux/amd64 \
                  -v "${tmpStage}:/stage" \
                  public.ecr.aws/sam/build-python3.12 \
                  pip3 install -r /stage/requirements-lambda.txt -t /stage/ --no-cache-dir --disable-pip-version-check`,
                { stdio: 'inherit' },
              );
              // Copy the staged output into the CDK output directory
              execSync(`cp -r ${tmpStage}/. ${outputDir}/`);
              execSync(`rm -rf ${tmpStage}`);
              return true;
            } catch (e) {
              return false;
            }
          },
        },
        command: [
          'bash', '-c',
          [
            'cp -r /asset-input/core /asset-output/',
            'cp -r /asset-input/adapters /asset-output/',
            'pip3 install -r /asset-input/requirements-lambda.txt -t /asset-output/ --no-cache-dir --disable-pip-version-check',
          ].join(' && '),
        ],
      },
    });

    // ── Common env vars for all handler Lambdas ──
    const commonEnv = {
      AGENTCOMMS_TABLE: props.table.tableName,
      AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      AGENTCOMMS_ENV: 'prod',
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
      // All handlers may invoke EmailAdapter.send() / .provision() (router picks adapter
      // based on 'to' format). Grant SES so the outbound path works without the separate
      // email-adapter SQS worker stack being present.
      fn.addToRolePolicy(new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [
          'ses:SendRawEmail',
          'ses:SendEmail',
          'ses:VerifyDomainDkim',
          'ses:GetSendQuota',
          'sesv2:SendEmail',
          'sesv2:CreateEmailIdentity',
          'sesv2:GetEmailIdentity',
          'sesv2:DeleteEmailIdentity',
        ],
        resources: ['*'],
      }));
      return fn;
    };

    // ── 13 Handler Lambdas ──
    // agents, channels, messages publish events → grant Kinesis write
    const agentsFn    = makeHandlerFn('AgentsFn',    'agents_handler',    true);
    // AgentsFn needs SSM read for Slack OAuth URL construction (bridge_start reads client_id)
    agentsFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['ssm:GetParameter'],
      resources: ['arn:aws:ssm:*:*:parameter/agentcomms/*/adapters/slack/*'],
    }));
    const channelsFn  = makeHandlerFn('ChannelsFn',  'channels_handler',  true);
    const messagesFn  = makeHandlerFn('MessagesFn',  'messages_handler',  true);
    const threadsFn   = makeHandlerFn('ThreadsFn',   'threads_handler',   false);
    const draftsFn    = makeHandlerFn('DraftsFn',    'drafts_handler',    false);
    const webhooksFn  = makeHandlerFn('WebhooksFn',  'webhooks_handler',  false);
    const waitFn      = makeHandlerFn('WaitFn',      'wait_handler',      false);
    const otpFn       = makeHandlerFn('OtpFn',       'otp_handler',       false);

    // ── Phase 2 Handler Lambdas ──

    // Dedicated KMS key for vault secrets (symmetric, no rotation needed for smoke tests)
    const vaultKey = new Key(this, 'VaultKey', {
      description: 'AgentComms vault secrets encryption key',
      enableKeyRotation: true,
    });

    // VaultFn: read/write DynamoDB + Kinesis + KMS for encrypt/decrypt
    const vaultFn = new LambdaFn(this, 'VaultFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'core.api.vault_handler.handler',
      code: lambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 512,
      environment: {
        ...commonEnv,
        AGENTCOMMS_VAULT_KMS_KEY_ID: vaultKey.keyId,
      },
    });
    props.table.grantReadWriteData(vaultFn);
    props.eventStream.grantWrite(vaultFn);
    vaultKey.grantEncryptDecrypt(vaultFn);

    // PersonasFn: read/write DynamoDB + Kinesis
    const personasFn = makeHandlerFn('PersonasFn', 'personas_handler', true);

    // DomainsFn: read/write DynamoDB + Kinesis + SES identity management
    const domainsFn = makeHandlerFn('DomainsFn', 'domains_handler', true);
    domainsFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'ses:CreateEmailIdentity',
        'ses:GetEmailIdentity',
        'ses:DeleteEmailIdentity',
        'sesv2:CreateEmailIdentity',
        'sesv2:GetEmailIdentity',
        'sesv2:DeleteEmailIdentity',
        'sesv2:PutEmailIdentityDkimAttributes',
        'sesv2:PutEmailIdentityMailFromAttributes',
      ],
      resources: ['*'],
    }));

    // AiFn: read/write DynamoDB + Kinesis + Bedrock InvokeModel
    const aiFn = makeHandlerFn('AiFn', 'ai_handler', false);
    aiFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['bedrock:InvokeModel'],
      resources: ['arn:aws:bedrock:us-east-1::foundation-model/*'],
    }));

    // PushNativeFn: read/write DynamoDB + Kinesis + SNS for push delivery
    const pushNativeFn = makeHandlerFn('PushNativeFn', 'push_native_handler', true);
    pushNativeFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'sns:CreatePlatformEndpoint',
        'sns:DeleteEndpoint',
        'sns:Publish',
      ],
      resources: ['*'],
    }));

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

    // ── Phase 2 routes ──

    // /v1/vault
    const vault = v1.addResource('vault');
    vault.addMethod('GET',  new LambdaIntegration(vaultFn), authMethodOptions);
    vault.addMethod('POST', new LambdaIntegration(vaultFn), authMethodOptions);

    // /v1/vault/{vault_id}
    const vaultItem = vault.addResource('{vault_id}');
    vaultItem.addMethod('GET',    new LambdaIntegration(vaultFn), authMethodOptions);
    vaultItem.addMethod('DELETE', new LambdaIntegration(vaultFn), authMethodOptions);

    // /v1/vault/{vault_id}/totp
    const vaultTotp = vaultItem.addResource('totp');
    vaultTotp.addMethod('GET', new LambdaIntegration(vaultFn), authMethodOptions);

    // /v1/personas
    const personas = v1.addResource('personas');
    personas.addMethod('GET',  new LambdaIntegration(personasFn), authMethodOptions);
    personas.addMethod('POST', new LambdaIntegration(personasFn), authMethodOptions);

    // /v1/personas/{persona_id}
    const personaItem = personas.addResource('{persona_id}');
    personaItem.addMethod('GET',    new LambdaIntegration(personasFn), authMethodOptions);
    personaItem.addMethod('PATCH',  new LambdaIntegration(personasFn), authMethodOptions);
    personaItem.addMethod('DELETE', new LambdaIntegration(personasFn), authMethodOptions);

    // /v1/agents/{agent_id}/personas
    const agentPersonas = agent.addResource('personas');
    agentPersonas.addMethod('POST', new LambdaIntegration(personasFn), authMethodOptions);

    // /v1/domains
    const domains = v1.addResource('domains');
    domains.addMethod('GET',  new LambdaIntegration(domainsFn), authMethodOptions);
    domains.addMethod('POST', new LambdaIntegration(domainsFn), authMethodOptions);

    // /v1/domains/{domain_id}
    const domainItem = domains.addResource('{domain_id}');
    domainItem.addMethod('GET',    new LambdaIntegration(domainsFn), authMethodOptions);
    domainItem.addMethod('DELETE', new LambdaIntegration(domainsFn), authMethodOptions);

    // /v1/domains/{domain_id}/verify
    const domainVerify = domainItem.addResource('verify');
    domainVerify.addMethod('POST', new LambdaIntegration(domainsFn), authMethodOptions);

    // /v1/domains/{domain_id}/zone-file
    const domainZoneFile = domainItem.addResource('zone-file');
    domainZoneFile.addMethod('GET', new LambdaIntegration(domainsFn), authMethodOptions);

    // /v1/agents/{agent_id}/ai/*
    const ai = agent.addResource('ai');

    const aiCategorize = ai.addResource('categorize');
    aiCategorize.addMethod('POST', new LambdaIntegration(aiFn), authMethodOptions);

    const aiExtract = ai.addResource('extract');
    aiExtract.addMethod('POST', new LambdaIntegration(aiFn), authMethodOptions);

    const aiSummarize = ai.addResource('summarize');
    aiSummarize.addMethod('POST', new LambdaIntegration(aiFn), authMethodOptions);

    const aiSearch = ai.addResource('search');
    aiSearch.addMethod('POST', new LambdaIntegration(aiFn), authMethodOptions);

    // /v1/agents/{agent_id}/push/*
    const push = agent.addResource('push');

    const pushDevices = push.addResource('devices');
    pushDevices.addMethod('GET',  new LambdaIntegration(pushNativeFn), authMethodOptions);
    pushDevices.addMethod('POST', new LambdaIntegration(pushNativeFn), authMethodOptions);

    const pushDevice = pushDevices.addResource('{device_id}');
    pushDevice.addMethod('DELETE', new LambdaIntegration(pushNativeFn), authMethodOptions);

    const pushSend = push.addResource('send');
    pushSend.addMethod('POST', new LambdaIntegration(pushNativeFn), authMethodOptions);

    // ── Phase 3: Slack native routes ──

    const slackNativeFn = new LambdaFn(this, 'SlackNativeFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'core.api.slack_native_handler.handler',
      code: lambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 512,
      environment: commonEnv,
    });
    props.table.grantReadWriteData(slackNativeFn);
    props.eventStream.grantWrite(slackNativeFn);
    slackNativeFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['ssm:GetParameter'],
      resources: ['arn:aws:ssm:*:*:parameter/agentcomms/*/adapters/slack/*'],
    }));

    // /v1/agents/{agent_id}/slack
    const slack = agent.addResource('slack');

    // /v1/agents/{agent_id}/slack/workspaces
    const slackWorkspaces = slack.addResource('workspaces');
    slackWorkspaces.addMethod('GET', new LambdaIntegration(slackNativeFn), authMethodOptions);

    // /v1/agents/{agent_id}/slack/workspaces/{team_id}
    const slackWorkspace = slackWorkspaces.addResource('{team_id}');

    // /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels
    const slackChannels = slackWorkspace.addResource('channels');
    slackChannels.addMethod('GET', new LambdaIntegration(slackNativeFn), authMethodOptions);

    // /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}
    const slackChannel = slackChannels.addResource('{channel_id}');

    // /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}/messages
    const slackChannelMessages = slackChannel.addResource('messages');
    slackChannelMessages.addMethod('GET',  new LambdaIntegration(slackNativeFn), authMethodOptions);
    slackChannelMessages.addMethod('POST', new LambdaIntegration(slackNativeFn), authMethodOptions);

    // /v1/agents/{agent_id}/slack/workspaces/{team_id}/users/{user_id}
    const slackUsers = slackWorkspace.addResource('users');
    const slackUser = slackUsers.addResource('{user_id}');

    // /v1/agents/{agent_id}/slack/workspaces/{team_id}/users/{user_id}/messages
    const slackDmMessages = slackUser.addResource('messages');
    slackDmMessages.addMethod('POST', new LambdaIntegration(slackNativeFn), authMethodOptions);

    // ── Phase 3: Slack webhook routes (inbound from Slack) ──
    if (props.enableSlack) {
      addSlackAdapter(this, {
        table: props.table,
        eventStream: props.eventStream,
        api: this.api,
      });
    }

    // ── Phase 3: Telegram native routes ──

    const telegramNativeFn = new LambdaFn(this, 'TelegramNativeFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'core.api.telegram_native_handler.handler',
      code: lambdaCode(),
      timeout: Duration.seconds(30),
      memorySize: 512,
      environment: commonEnv,
    });
    props.table.grantReadWriteData(telegramNativeFn);
    props.eventStream.grantWrite(telegramNativeFn);
    telegramNativeFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['ssm:GetParameter'],
      resources: ['arn:aws:ssm:*:*:parameter/agentcomms/*/adapters/telegram/tokens/*'],
    }));

    // /v1/agents/{agent_id}/telegram
    const telegram = agent.addResource('telegram');

    // /v1/agents/{agent_id}/telegram/chats
    const telegramChats = telegram.addResource('chats');
    telegramChats.addMethod('GET', new LambdaIntegration(telegramNativeFn), authMethodOptions);

    // /v1/agents/{agent_id}/telegram/chats/{chat_id}
    const telegramChat = telegramChats.addResource('{chat_id}');

    // /v1/agents/{agent_id}/telegram/chats/{chat_id}/messages
    const telegramChatMessages = telegramChat.addResource('messages');
    telegramChatMessages.addMethod('GET',  new LambdaIntegration(telegramNativeFn), authMethodOptions);
    telegramChatMessages.addMethod('POST', new LambdaIntegration(telegramNativeFn), authMethodOptions);

    // ── Phase 3: Telegram webhook route (inbound from Telegram Bot API) ──
    if (props.enableTelegram) {
      addTelegramAdapter(this, {
        table: props.table,
        eventStream: props.eventStream,
        api: this.api,
      });
    }
  }
}
