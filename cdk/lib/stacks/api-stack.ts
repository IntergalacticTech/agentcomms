import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as sns from "aws-cdk-lib/aws-sns";
import * as sns_subs from "aws-cdk-lib/aws-sns-subscriptions";
import * as lambda_events from "aws-cdk-lib/aws-lambda-event-sources";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ses from "aws-cdk-lib/aws-ses";
import * as ses_actions from "aws-cdk-lib/aws-ses-actions";
import * as path from "path";

export interface ApiStackProps extends cdk.StackProps {
  stage: string;
  table: dynamodb.Table;
  rawEmailBucket: s3.Bucket;
  bodiesBucket: s3.Bucket;
  attachmentsBucket: s3.Bucket;
  sendQueue: sqs.Queue;
  webhookQueue: sqs.Queue;
  bounceTopic: sns.Topic;
  complaintTopic: sns.Topic;
  deliveryTopic: sns.Topic;
  userPoolId: string;
  userPoolClientId: string;
}

export class ApiStack extends cdk.Stack {
  public readonly api: apigateway.RestApi;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const lambdasDir = path.join(__dirname, "..", "..", "..", "lambdas");

    const commonEnv: Record<string, string> = {
      TABLE_NAME: props.table.tableName,
      EMAIL_BUCKET: props.rawEmailBucket.bucketName,
      ATTACHMENT_BUCKET: props.attachmentsBucket.bucketName,
      BODY_BUCKET: props.bodiesBucket.bucketName,
      SEND_QUEUE_URL: props.sendQueue.queueUrl,
      SES_CONFIG_SET: "victorymail-default",
      USER_POOL_ID: props.userPoolId,
      WEBHOOK_QUEUE_URL: props.webhookQueue.queueUrl,
    };

    // Helper to create a Lambda function with common config
    const createFn = (
      name: string,
      handlerPath: string,
      opts?: { timeout?: number; memory?: number }
    ): lambda.Function => {
      const fn = new lambda.Function(this, name, {
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: `${handlerPath}.handler`,
        code: lambda.Code.fromAsset(lambdasDir),
        environment: commonEnv,
        timeout: cdk.Duration.seconds(opts?.timeout ?? 30),
        memorySize: opts?.memory ?? 256,
      });
      props.table.grantReadWriteData(fn);
      props.rawEmailBucket.grantReadWrite(fn);
      props.bodiesBucket.grantReadWrite(fn);
      props.attachmentsBucket.grantReadWrite(fn);
      return fn;
    };

    // ── Lambda Functions ───────────────────────────────────────────────

    const authorizerFn = createFn("AuthorizerFn", "authorizer.handler");
    const signupFn = createFn("SignupFn", "signup.handler");
    const orgFn = createFn("OrgFn", "organizations.handler");
    const apiKeysFn = createFn("ApiKeysFn", "api_keys.handler");
    const podsFn = createFn("PodsFn", "pods.handler");
    const inboxesFn = createFn("InboxesFn", "inboxes.handler");
    const messagesFn = createFn("MessagesFn", "messages.handler", {
      timeout: 60,
      memory: 512,
    });
    props.sendQueue.grantSendMessages(messagesFn);

    const threadsFn = createFn("ThreadsFn", "threads.handler");
    const draftsFn = createFn("DraftsFn", "drafts.handler");
    const domainsFn = createFn("DomainsFn", "domains.handler");
    domainsFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "ses:VerifyDomainIdentity",
          "ses:VerifyDomainDkim",
          "ses:DeleteIdentity",
          "ses:GetIdentityVerificationAttributes",
        ],
        resources: ["*"],
      })
    );

    const webhooksFn = createFn("WebhooksFn", "webhooks.handler");
    const billingFn = createFn("BillingFn", "billing.handler");
    const waitFn = createFn("WaitFn", "wait.handler", {
      timeout: 30,
      memory: 256,
    });
    const attachmentsFn = createFn("AttachmentsFn", "attachments.handler");
    const listsFn = createFn("ListsFn", "lists.handler");
    const searchFn = createFn("SearchFn", "search.handler");
    const aiFn = createFn("AiFn", "ai.handler", { timeout: 60, memory: 512 });
    aiFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: ["*"],
      })
    );
    const metricsFn = createFn("MetricsFn", "metrics.handler");

    // Webhook delivery worker (SQS consumer)
    const webhookWorkerFn = createFn(
      "WebhookWorkerFn",
      "webhook_worker.handler",
      { timeout: 30, memory: 256 }
    );
    webhookWorkerFn.addEventSource(
      new lambda_events.SqsEventSource(props.webhookQueue, { batchSize: 1 })
    );

    // Console auth Lambda (Cognito operations)
    const consoleAuthFn = new lambda.Function(this, "ConsoleAuthFn", {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "console_auth.handler.handler",
      code: lambda.Code.fromAsset(lambdasDir),
      environment: {
        ...commonEnv,
        COGNITO_CLIENT_ID: props.userPoolClientId,
      },
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });
    props.table.grantReadWriteData(consoleAuthFn);
    consoleAuthFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "cognito-idp:SignUp",
          "cognito-idp:ConfirmSignUp",
          "cognito-idp:ResendConfirmationCode",
          "cognito-idp:InitiateAuth",
          "cognito-idp:AdminUpdateUserAttributes",
        ],
        resources: ["*"],
      })
    );

    // Workers
    const inboundFn = createFn(
      "InboundProcessorFn",
      "inbound_processor.handler",
      { timeout: 60, memory: 1024 }
    );

    const outboundFn = createFn(
      "OutboundWorkerFn",
      "outbound_worker.handler",
      { timeout: 60, memory: 512 }
    );
    outboundFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: ["*"],
      })
    );
    outboundFn.addEventSource(
      new lambda_events.SqsEventSource(props.sendQueue, { batchSize: 1 })
    );

    const bounceFn = createFn(
      "BounceProcessorFn",
      "bounce_processor.handler"
    );
    props.bounceTopic.addSubscription(
      new sns_subs.LambdaSubscription(bounceFn)
    );
    props.complaintTopic.addSubscription(
      new sns_subs.LambdaSubscription(bounceFn)
    );

    // ── SES Inbound Receipt Rules ──────────────────────────────────────

    // Grant SES permission to write to S3 bucket
    props.rawEmailBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("ses.amazonaws.com")],
        actions: ["s3:PutObject"],
        resources: [props.rawEmailBucket.arnForObjects("*")],
        conditions: {
          StringEquals: {
            "AWS:SourceAccount": this.account,
          },
        },
      })
    );

    // Grant SES permission to invoke the inbound Lambda
    inboundFn.addPermission("SESInvoke", {
      principal: new iam.ServicePrincipal("ses.amazonaws.com"),
      sourceAccount: this.account,
    });

    // Receipt rule set
    const ruleSet = new ses.ReceiptRuleSet(this, "InboundRuleSet", {
      receiptRuleSetName: "victorymail-inbound",
    });

    // Catch-all rule for victorymail.dev
    ruleSet.addRule("VictorymailCatchAll", {
      recipients: ["victorymail.dev"],
      scanEnabled: true,
      actions: [
        new ses_actions.S3({
          bucket: props.rawEmailBucket,
          objectKeyPrefix: "inbound/",
        }),
        new ses_actions.Lambda({
          function: inboundFn,
          invocationType: ses_actions.LambdaInvocationType.EVENT,
        }),
      ],
    });

    // ── API Gateway ────────────────────────────────────────────────────

    this.api = new apigateway.RestApi(this, "FreemailApi", {
      restApiName: "FreeMail API",
      description: "FreeMail email platform API",
      deployOptions: {
        stageName: "v1",
        throttlingRateLimit: 1000,
        throttlingBurstLimit: 2000,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          "Content-Type",
          "x-api-key",
          "Authorization",
        ],
      },
    });

    // Token Authorizer
    const authorizer = new apigateway.TokenAuthorizer(
      this,
      "ApiKeyAuthorizer",
      {
        handler: authorizerFn,
        identitySource: "method.request.header.x-api-key",
        resultsCacheTtl: cdk.Duration.minutes(5),
      }
    );

    const authOpts: apigateway.MethodOptions = {
      authorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    };

    const lambdaIntegration = (fn: lambda.Function) =>
      new apigateway.LambdaIntegration(fn);

    // ── Routes: Signup (no auth) ───────────────────────────────────────

    const agent = this.api.root.addResource("agent");
    agent
      .addResource("signup")
      .addMethod("POST", lambdaIntegration(signupFn));
    agent
      .addResource("verify")
      .addMethod("POST", lambdaIntegration(signupFn));

    // ── Routes: Organizations ──────────────────────────────────────────

    const orgs = this.api.root.addResource("organizations");
    orgs
      .addResource("me")
      .addMethod("GET", lambdaIntegration(orgFn), authOpts);

    // ── Routes: API Keys ───────────────────────────────────────────────

    const apiKeysRes = this.api.root.addResource("api-keys");
    apiKeysRes.addMethod("GET", lambdaIntegration(apiKeysFn), authOpts);
    apiKeysRes.addMethod("POST", lambdaIntegration(apiKeysFn), authOpts);
    apiKeysRes
      .addResource("{id}")
      .addMethod("DELETE", lambdaIntegration(apiKeysFn), authOpts);

    // ── Routes: Pods ───────────────────────────────────────────────────

    const pods = this.api.root.addResource("pods");
    pods.addMethod("GET", lambdaIntegration(podsFn), authOpts);
    pods.addMethod("POST", lambdaIntegration(podsFn), authOpts);
    const podById = pods.addResource("{id}");
    podById.addMethod("GET", lambdaIntegration(podsFn), authOpts);
    podById.addMethod("DELETE", lambdaIntegration(podsFn), authOpts);

    // ── Routes: Inboxes ────────────────────────────────────────────────

    const inboxes = this.api.root.addResource("inboxes");
    inboxes.addMethod("GET", lambdaIntegration(inboxesFn), authOpts);
    inboxes.addMethod("POST", lambdaIntegration(inboxesFn), authOpts);
    const inboxById = inboxes.addResource("{id}");
    inboxById.addMethod("GET", lambdaIntegration(inboxesFn), authOpts);
    inboxById.addMethod("PATCH", lambdaIntegration(inboxesFn), authOpts);
    inboxById.addMethod("DELETE", lambdaIntegration(inboxesFn), authOpts);

    // ── Routes: Messages ───────────────────────────────────────────────

    const messages = inboxById.addResource("messages");
    messages.addMethod("GET", lambdaIntegration(messagesFn), authOpts);
    messages.addMethod("POST", lambdaIntegration(messagesFn), authOpts);
    const msgById = messages.addResource("{mid}");
    msgById.addMethod("GET", lambdaIntegration(messagesFn), authOpts);
    msgById.addMethod("PATCH", lambdaIntegration(messagesFn), authOpts);
    msgById
      .addResource("reply")
      .addMethod("POST", lambdaIntegration(messagesFn), authOpts);
    msgById
      .addResource("reply-all")
      .addMethod("POST", lambdaIntegration(messagesFn), authOpts);
    msgById
      .addResource("forward")
      .addMethod("POST", lambdaIntegration(messagesFn), authOpts);

    // ── Routes: Threads ────────────────────────────────────────────────

    const threads = inboxById.addResource("threads");
    threads.addMethod("GET", lambdaIntegration(threadsFn), authOpts);
    const threadById = threads.addResource("{tid}");
    threadById.addMethod("GET", lambdaIntegration(threadsFn), authOpts);
    threadById.addMethod("PATCH", lambdaIntegration(threadsFn), authOpts);
    threadById.addMethod("DELETE", lambdaIntegration(threadsFn), authOpts);

    // ── Routes: Drafts ─────────────────────────────────────────────────

    const drafts = inboxById.addResource("drafts");
    drafts.addMethod("GET", lambdaIntegration(draftsFn), authOpts);
    drafts.addMethod("POST", lambdaIntegration(draftsFn), authOpts);
    const draftById = drafts.addResource("{did}");
    draftById.addMethod("GET", lambdaIntegration(draftsFn), authOpts);
    draftById.addMethod("PATCH", lambdaIntegration(draftsFn), authOpts);
    draftById.addMethod("DELETE", lambdaIntegration(draftsFn), authOpts);
    draftById
      .addResource("send")
      .addMethod("POST", lambdaIntegration(draftsFn), authOpts);

    // ── Routes: Domains ────────────────────────────────────────────────

    const domains = this.api.root.addResource("domains");
    domains.addMethod("GET", lambdaIntegration(domainsFn), authOpts);
    domains.addMethod("POST", lambdaIntegration(domainsFn), authOpts);
    const domainById = domains.addResource("{id}");
    domainById.addMethod("GET", lambdaIntegration(domainsFn), authOpts);
    domainById.addMethod("PATCH", lambdaIntegration(domainsFn), authOpts);
    domainById.addMethod("DELETE", lambdaIntegration(domainsFn), authOpts);
    domainById
      .addResource("verify")
      .addMethod("POST", lambdaIntegration(domainsFn), authOpts);
    domainById
      .addResource("zone-file")
      .addMethod("GET", lambdaIntegration(domainsFn), authOpts);

    // ── Routes: Webhooks ───────────────────────────────────────────────

    const webhooks = this.api.root.addResource("webhooks");
    webhooks.addMethod("GET", lambdaIntegration(webhooksFn), authOpts);
    webhooks.addMethod("POST", lambdaIntegration(webhooksFn), authOpts);
    const webhookById = webhooks.addResource("{id}");
    webhookById.addMethod("GET", lambdaIntegration(webhooksFn), authOpts);
    webhookById.addMethod(
      "PATCH",
      lambdaIntegration(webhooksFn),
      authOpts
    );
    webhookById.addMethod(
      "DELETE",
      lambdaIntegration(webhooksFn),
      authOpts
    );

    // ── Routes: Wait / OTP ───────────────────────────────────────────

    inboxById
      .addResource("wait")
      .addMethod("POST", lambdaIntegration(waitFn), authOpts);
    inboxById
      .addResource("extract-otp")
      .addMethod("POST", lambdaIntegration(waitFn), authOpts);

    // ── Routes: Attachments ────────────────────────────────────────────

    const attachments = msgById.addResource("attachments");
    attachments.addMethod(
      "GET",
      lambdaIntegration(attachmentsFn),
      authOpts
    );
    attachments
      .addResource("{aid}")
      .addMethod("GET", lambdaIntegration(attachmentsFn), authOpts);

    // ── Routes: Lists ──────────────────────────────────────────────────

    const lists = this.api.root.addResource("lists");
    lists.addMethod("GET", lambdaIntegration(listsFn), authOpts);
    lists.addMethod("POST", lambdaIntegration(listsFn), authOpts);
    const listById = lists.addResource("{id}");
    listById.addMethod("GET", lambdaIntegration(listsFn), authOpts);
    listById.addMethod("DELETE", lambdaIntegration(listsFn), authOpts);
    const listMembers = listById.addResource("members");
    listMembers.addMethod("POST", lambdaIntegration(listsFn), authOpts);
    listMembers
      .addResource("{email}")
      .addMethod("DELETE", lambdaIntegration(listsFn), authOpts);

    // ── Routes: Console Auth ─────────────────────────────────────────

    const console = this.api.root.addResource("console");
    console
      .addResource("signup")
      .addMethod("POST", lambdaIntegration(consoleAuthFn));
    console
      .addResource("login")
      .addMethod("POST", lambdaIntegration(consoleAuthFn));
    console
      .addResource("verify")
      .addMethod("POST", lambdaIntegration(consoleAuthFn));
    console
      .addResource("resend-code")
      .addMethod("POST", lambdaIntegration(consoleAuthFn));
    console
      .addResource("refresh")
      .addMethod("POST", lambdaIntegration(consoleAuthFn));
    console
      .addResource("me")
      .addMethod("GET", lambdaIntegration(consoleAuthFn), authOpts);

    // ── Routes: Billing ──────────────────────────────────────────────

    const billing = this.api.root.addResource("billing");
    billing
      .addResource("checkout")
      .addMethod("POST", lambdaIntegration(billingFn), authOpts);
    billing
      .addResource("portal")
      .addMethod("POST", lambdaIntegration(billingFn), authOpts);
    billing
      .addResource("status")
      .addMethod("GET", lambdaIntegration(billingFn), authOpts);
    billing
      .addResource("webhook")
      .addMethod("POST", lambdaIntegration(billingFn)); // No auth - Stripe signs it

    // ── Routes: Search ───────────────────────────────────────────────

    this.api.root
      .addResource("search")
      .addMethod("POST", lambdaIntegration(searchFn), authOpts);

    // ── Routes: AI ──────────────────────────────────────────────────

    const ai = this.api.root.addResource("ai");
    ai.addResource("categorize")
      .addMethod("POST", lambdaIntegration(aiFn), authOpts);
    ai.addResource("extract")
      .addMethod("POST", lambdaIntegration(aiFn), authOpts);
    ai.addResource("summarize")
      .addMethod("POST", lambdaIntegration(aiFn), authOpts);

    // ── Routes: Metrics ────────────────────────────────────────────────

    const metrics = this.api.root.addResource("metrics");
    metrics
      .addResource("query")
      .addMethod("POST", lambdaIntegration(metricsFn), authOpts);
    metrics
      .addResource("usage")
      .addMethod("GET", lambdaIntegration(metricsFn), authOpts);

    // ── SQS Send Permissions for Webhook Publishing ────────────────

    props.webhookQueue.grantSendMessages(messagesFn);
    props.webhookQueue.grantSendMessages(inboundFn);
    props.webhookQueue.grantSendMessages(inboxesFn);

    // ── Outputs ────────────────────────────────────────────────────────

    new cdk.CfnOutput(this, "ApiUrl", {
      value: this.api.url,
      description: "FreeMail API URL",
    });
  }
}
