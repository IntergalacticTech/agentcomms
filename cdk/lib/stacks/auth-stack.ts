import * as cdk from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import { Construct } from "constructs";

export interface AuthStackProps extends cdk.StackProps {
  stage: string;
}

export class AuthStack extends cdk.Stack {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;

  constructor(scope: Construct, id: string, props: AuthStackProps) {
    super(scope, id, props);

    this.userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: `victorymail-users-${props.stage}`,
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
        fullname: { required: false, mutable: true },
      },
      customAttributes: {
        org_id: new cognito.StringAttribute({ mutable: true }),
      },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      // SES email delivery is enabled via context flag `sesEmailEnabled`.
      // Requires victorymail.dev to be a verified SES identity first.
      // Default: use Cognito's built-in email (50/day limit, no verification needed).
      ...(scope.node.tryGetContext("sesEmailEnabled")
        ? {
            email: cognito.UserPoolEmail.withSES({
              fromEmail: "noreply@victorymail.dev",
              fromName: "FreeMail",
              sesRegion: "us-east-1",
              sesVerifiedDomain: "victorymail.dev",
            }),
          }
        : {}),
      userVerification: {
        emailSubject: "Verify your FreeMail account",
        emailBody:
          "Welcome to FreeMail! Your verification code is {####}",
        emailStyle: cognito.VerificationEmailStyle.CODE,
      },
    });

    // App client for the developer console (SPA - no secret)
    this.userPoolClient = this.userPool.addClient("ConsoleClient", {
      userPoolClientName: "victorymail-console",
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
      oAuth: {
        flows: { authorizationCodeGrant: true, implicitCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [
          "http://localhost:5173/auth/callback", // dev
          "https://console.victorymail.dev/auth/callback", // prod
        ],
        logoutUrls: [
          "http://localhost:5173/",
          "https://console.victorymail.dev/",
        ],
      },
      preventUserExistenceErrors: true,
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
    });

    // Cognito domain for hosted UI
    this.userPool.addDomain("CognitoDomain", {
      cognitoDomain: { domainPrefix: `victorymail-${props.stage}` },
    });

    // Outputs
    new cdk.CfnOutput(this, "UserPoolId", {
      value: this.userPool.userPoolId,
    });
    new cdk.CfnOutput(this, "UserPoolClientId", {
      value: this.userPoolClient.userPoolClientId,
    });
    new cdk.CfnOutput(this, "CognitoRegion", { value: this.region });
  }
}
