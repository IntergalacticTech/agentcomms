import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as sns from "aws-cdk-lib/aws-sns";
import * as ses from "aws-cdk-lib/aws-ses";

export interface EmailStackProps extends cdk.StackProps {
  stage: string;
}

export class EmailStack extends cdk.Stack {
  public readonly bounceTopic: sns.Topic;
  public readonly complaintTopic: sns.Topic;
  public readonly deliveryTopic: sns.Topic;
  public readonly configSet: ses.CfnConfigurationSet;

  constructor(scope: Construct, id: string, props: EmailStackProps) {
    super(scope, id, props);

    // ── SNS Topics ─────────────────────────────────────────────────────

    this.bounceTopic = new sns.Topic(this, "BounceTopic", {
      topicName: "victorymail-ses-bounces",
    });

    this.complaintTopic = new sns.Topic(this, "ComplaintTopic", {
      topicName: "victorymail-ses-complaints",
    });

    this.deliveryTopic = new sns.Topic(this, "DeliveryTopic", {
      topicName: "victorymail-ses-deliveries",
    });

    // ── SES Configuration Set ──────────────────────────────────────────

    this.configSet = new ses.CfnConfigurationSet(this, "ConfigSet", {
      name: "victorymail-default",
    });

    // Bounce event destination
    new ses.CfnConfigurationSetEventDestination(
      this,
      "BounceEventDestination",
      {
        configurationSetName: this.configSet.name!,
        eventDestination: {
          name: "bounce-to-sns",
          enabled: true,
          matchingEventTypes: ["bounce"],
          snsDestination: {
            topicArn: this.bounceTopic.topicArn,
          },
        },
      }
    );

    // Complaint event destination
    new ses.CfnConfigurationSetEventDestination(
      this,
      "ComplaintEventDestination",
      {
        configurationSetName: this.configSet.name!,
        eventDestination: {
          name: "complaint-to-sns",
          enabled: true,
          matchingEventTypes: ["complaint"],
          snsDestination: {
            topicArn: this.complaintTopic.topicArn,
          },
        },
      }
    );

    // ── Outputs ────────────────────────────────────────────────────────

    new cdk.CfnOutput(this, "BounceTopicArn", {
      value: this.bounceTopic.topicArn,
    });
    new cdk.CfnOutput(this, "ComplaintTopicArn", {
      value: this.complaintTopic.topicArn,
    });
    new cdk.CfnOutput(this, "DeliveryTopicArn", {
      value: this.deliveryTopic.topicArn,
    });
    new cdk.CfnOutput(this, "ConfigSetName", {
      value: this.configSet.name!,
    });
  }
}
