import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface CicdStackProps extends cdk.StackProps {
  stage: string;
}

export class CicdStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: CicdStackProps) {
    super(scope, id, props);

    // GitHub OIDC Provider - import existing (one per account)
    const provider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
      this,
      'GitHubOIDC',
      `arn:aws:iam::${this.account}:oidc-provider/token.actions.githubusercontent.com`,
    );

    // Deploy Role for GitHub Actions
    const deployRole = new iam.Role(this, 'GitHubActionsDeployRole', {
      roleName: 'GitHubActionsDeployRole',
      assumedBy: new iam.WebIdentityPrincipal(
        provider.openIdConnectProviderArn,
        {
          StringLike: {
            'token.actions.githubusercontent.com:sub': 'repo:IntergalacticTech/FreeMail.ai:*',
          },
          StringEquals: {
            'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          },
        },
      ),
      maxSessionDuration: cdk.Duration.hours(1),
    });

    // CDK deploy permissions
    deployRole.addManagedPolicy(
      iam.ManagedPolicy.fromManagedPolicyArn(this, 'AdminPolicy', 'arn:aws:iam::aws:policy/AdministratorAccess')
    );
    // Note: In production, scope this down to specific CDK deploy permissions
  }
}
