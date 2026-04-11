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

    // ── Outputs ────────────────────────────────────────────────────────

    new cdk.CfnOutput(this, "ApiUrl", {
      value: this.api.url,
      description: "FreeMail API URL",
    });
  }
}
