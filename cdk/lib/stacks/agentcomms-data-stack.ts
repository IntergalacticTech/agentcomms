// cdk/lib/stacks/agentcomms-data-stack.ts
import { Stack, StackProps, RemovalPolicy, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import {
  Table, AttributeType, BillingMode, ProjectionType, TableEncryption,
} from 'aws-cdk-lib/aws-dynamodb';
import {
  Bucket, BucketEncryption, BlockPublicAccess, LifecycleRule,
  StorageClass,
} from 'aws-cdk-lib/aws-s3';

export interface AgentCommsDataStackProps extends StackProps {
  envName?: string;    // "prod" | "staging" | "dev"; affects bucket names
}

export class AgentCommsDataStack extends Stack {
  public readonly table: Table;
  public readonly rawInboundBucket: Bucket;
  public readonly bodiesBucket: Bucket;
  public readonly attachmentsBucket: Bucket;

  constructor(scope: Construct, id: string, props: AgentCommsDataStackProps = {}) {
    super(scope, id, props);
    const envName = props.envName ?? 'prod';

    // ── DynamoDB single table ──
    this.table = new Table(this, 'AgentCommsTable', {
      tableName: 'agentcomms',
      partitionKey: { name: 'PK', type: AttributeType.STRING },
      sortKey:      { name: 'SK', type: AttributeType.STRING },
      billingMode:  BillingMode.PAY_PER_REQUEST,
      encryption:   TableEncryption.AWS_MANAGED,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',
    });
    for (const i of [1, 2, 3, 4, 5, 6, 7]) {
      this.table.addGlobalSecondaryIndex({
        indexName:    `GSI${i}`,
        partitionKey: { name: `gsi${i}_pk`, type: AttributeType.STRING },
        sortKey:      { name: `gsi${i}_sk`, type: AttributeType.STRING },
        projectionType: ProjectionType.ALL,
      });
    }

    // ── S3 buckets ──
    const lifecycle: LifecycleRule = {
      transitions: [
        { storageClass: StorageClass.INFREQUENT_ACCESS, transitionAfter: Duration.days(30) },
        { storageClass: StorageClass.GLACIER,            transitionAfter: Duration.days(90) },
      ],
    };
    this.rawInboundBucket = new Bucket(this, 'RawInbound', {
      bucketName: `agentcomms-raw-inbound-${envName}-${this.account}`,
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [lifecycle],
      removalPolicy: RemovalPolicy.RETAIN,
      versioned: false,
    });
    this.bodiesBucket = new Bucket(this, 'Bodies', {
      bucketName: `agentcomms-bodies-${envName}-${this.account}`,
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [lifecycle],
      removalPolicy: RemovalPolicy.RETAIN,
    });
    this.attachmentsBucket = new Bucket(this, 'Attachments', {
      bucketName: `agentcomms-attachments-${envName}-${this.account}`,
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [lifecycle],
      removalPolicy: RemovalPolicy.RETAIN,
    });
  }
}
