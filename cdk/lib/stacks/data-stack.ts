// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as s3 from "aws-cdk-lib/aws-s3";

export interface DataStackProps extends cdk.StackProps {
  stage: string;
}

export class DataStack extends cdk.Stack {
  public readonly table: dynamodb.Table;
  public readonly rawEmailBucket: s3.Bucket;
  public readonly bodiesBucket: s3.Bucket;
  public readonly attachmentsBucket: s3.Bucket;
  public readonly vaultBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    // ── DynamoDB Single Table ──────────────────────────────────────────

    this.table = new dynamodb.Table(this, "Table", {
      tableName: "victorymail",
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      timeToLiveAttribute: "ttl",
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI1: API key by hash, pods in org, inboxes in pod, threads in inbox
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI1",
      partitionKey: { name: "GSI1PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI1SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI2: Email address routing for inbound
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI2",
      partitionKey: { name: "GSI2PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI2SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ["org_id", "pod_id", "status"],
    });

    // GSI3: Org-wide messages
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI3",
      partitionKey: { name: "GSI3PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI3SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: [
        "inbox_id",
        "thread_id",
        "direction",
        "from_addr",
        "subject",
        "snippet",
        "is_read",
        "category",
        "received_at",
      ],
    });

    // GSI4: WebSocket fan-out
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI4",
      partitionKey: { name: "GSI4PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI4SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ["connection_id", "org_id"],
    });

    // GSI5: AI usage
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI5",
      partitionKey: { name: "GSI5PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI5SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: [
        "model_id",
        "operation",
        "input_tokens",
        "output_tokens",
        "cost_usd",
      ],
    });

    // GSI6: SES message ID lookup
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI6",
      partitionKey: { name: "GSI6PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI6SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ["inbox_id", "org_id"],
    });

    // ── S3 Buckets ─────────────────────────────────────────────────────

    const account = cdk.Stack.of(this).account;

    // Raw inbound email - 7 day expiry on inbound/ prefix
    this.rawEmailBucket = new s3.Bucket(this, "RawEmailBucket", {
      bucketName: `victorymail-raw-email-${account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          prefix: "inbound/",
          expiration: cdk.Duration.days(7),
        },
      ],
    });

    // Email bodies - IA transition at 90 days
    this.bodiesBucket = new s3.Bucket(this, "BodiesBucket", {
      bucketName: `victorymail-bodies-${account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
      ],
    });

    // Attachments - IA transition at 90 days
    this.attachmentsBucket = new s3.Bucket(this, "AttachmentsBucket", {
      bucketName: `victorymail-attachments-${account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
      ],
    });

    // Vault bucket stores KMS-wrapped ciphertext blobs for the secret vault
    // feature. Each secret is one S3 object encrypted with a per-org KMS CMK;
    // S3-level SSE is belt-and-suspenders. Retain on stack delete so secrets
    // cannot be accidentally destroyed.
    this.vaultBucket = new s3.Bucket(this, "VaultBucket", {
      bucketName: `victorymail-vault-${account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── Outputs ────────────────────────────────────────────────────────

    new cdk.CfnOutput(this, "TableName", { value: this.table.tableName });
    new cdk.CfnOutput(this, "TableArn", { value: this.table.tableArn });
    new cdk.CfnOutput(this, "RawEmailBucketName", {
      value: this.rawEmailBucket.bucketName,
    });
    new cdk.CfnOutput(this, "BodiesBucketName", {
      value: this.bodiesBucket.bucketName,
    });
    new cdk.CfnOutput(this, "AttachmentsBucketName", {
      value: this.attachmentsBucket.bucketName,
    });
    new cdk.CfnOutput(this, "VaultBucketName", {
      value: this.vaultBucket.bucketName,
    });
  }
}
