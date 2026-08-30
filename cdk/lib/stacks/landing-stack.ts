// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as path from "path";

export interface LandingStackProps extends cdk.StackProps {
  stage: string;
  siteId?: string;
}

export class LandingStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: LandingStackProps) {
    super(scope, id, props);

    const siteId = props.siteId ?? "victorymail";

    const siteBucket = new s3.Bucket(this, "LandingBucket", {
      bucketName: `${siteId}-landing-${this.account}-${props.stage}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const distribution = new cloudfront.Distribution(
      this,
      "LandingDistribution",
      {
        defaultBehavior: {
          origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
          viewerProtocolPolicy:
            cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        },
        defaultRootObject: "index.html",
        errorResponses: [
          {
            httpStatus: 404,
            responseHttpStatus: 200,
            responsePagePath: "/404.html",
            ttl: cdk.Duration.minutes(5),
          },
        ],
      }
    );

    const landingDir = path.join(__dirname, "..", "..", "..", "landing");
    new s3deploy.BucketDeployment(this, "DeployLanding", {
      sources: [s3deploy.Source.asset(landingDir)],
      destinationBucket: siteBucket,
      distribution,
      distributionPaths: ["/*"],
    });

    new cdk.CfnOutput(this, "LandingUrl", {
      value: `https://${distribution.distributionDomainName}`,
      description: "Landing page URL",
    });
  }
}
