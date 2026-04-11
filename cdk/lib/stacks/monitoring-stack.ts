import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import { Construct } from "constructs";

export interface MonitoringStackProps extends cdk.StackProps {
  stage: string;
}

export class MonitoringStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MonitoringStackProps) {
    super(scope, id, props);

    const dashboard = new cloudwatch.Dashboard(this, "FreemailDashboard", {
      dashboardName: `freemail-${props.stage}`,
    });

    // API Gateway metrics
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "API Requests",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ApiGateway",
            metricName: "Count",
            dimensionsMap: { ApiName: "FreeMail API" },
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "API Latency (p50/p99)",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ApiGateway",
            metricName: "Latency",
            dimensionsMap: { ApiName: "FreeMail API" },
            statistic: "p50",
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "AWS/ApiGateway",
            metricName: "Latency",
            dimensionsMap: { ApiName: "FreeMail API" },
            statistic: "p99",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
    );

    // API errors and DynamoDB
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "API 4xx/5xx Errors",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ApiGateway",
            metricName: "4XXError",
            dimensionsMap: { ApiName: "FreeMail API" },
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "AWS/ApiGateway",
            metricName: "5XXError",
            dimensionsMap: { ApiName: "FreeMail API" },
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "DynamoDB Read/Write Units",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/DynamoDB",
            metricName: "ConsumedReadCapacityUnits",
            dimensionsMap: { TableName: "victorymail" },
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "AWS/DynamoDB",
            metricName: "ConsumedWriteCapacityUnits",
            dimensionsMap: { TableName: "victorymail" },
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
    );

    // SQS and Lambda
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "SQS Send Queue Depth",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/SQS",
            metricName: "ApproximateNumberOfMessagesVisible",
            dimensionsMap: { QueueName: "victorymail-send-queue.fifo" },
            statistic: "Maximum",
            period: cdk.Duration.minutes(1),
          }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "Lambda Errors (All Functions)",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/Lambda",
            metricName: "Errors",
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
    );
  }
}
