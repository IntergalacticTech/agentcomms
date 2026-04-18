// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

// cdk/test/sunset-redirect-stack.test.ts
//
// Minimal CDK synthesis tests for SunsetRedirectStack.
//
import { App } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { SunsetRedirectStack } from '../lib/stacks/sunset-redirect-stack';

const STACK_PROPS = {
  targetApiUrl:  'https://api.agentcomms.dev',
  sunsetDate:    '2026-07-17T00:00:00Z',
  hostedZoneId:  'Z1ABCDEFG12345',
  legacyHostname: 'api.victorymail.dev',
  env: { region: 'us-east-1', account: '732770059798' },
};

function buildTemplate() {
  const app = new App();
  const stack = new SunsetRedirectStack(app, 'SunsetTest', STACK_PROPS);
  return { template: Template.fromStack(stack), stack };
}

describe('SunsetRedirectStack', () => {
  const { template } = buildTemplate();

  // ── CloudFront ──────────────────────────────────────────────────────────

  test('creates a CloudFront distribution with the legacy custom domain', () => {
    template.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        Aliases: Match.arrayWith(['api.victorymail.dev']),
        Enabled: true,
      }),
    });
  });

  test('CloudFront distribution has CachingDisabled cache policy (no redirect caching)', () => {
    // CachingDisabled managed policy ID: 4135ea2d-6df8-44a3-9df3-4b5a84be39ad
    template.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultCacheBehavior: Match.objectLike({
          CachePolicyId: '4135ea2d-6df8-44a3-9df3-4b5a84be39ad',
        }),
      }),
    });
  });

  // ── Lambda@Edge ─────────────────────────────────────────────────────────

  test('creates a Lambda function for the viewer-request edge handler', () => {
    // Edge functions must be us-east-1 Node.js Lambdas
    template.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'nodejs18.x',
      Handler: 'index.handler',
    });
  });

  test('Lambda@Edge handler code contains the sunset date', () => {
    const lambdas = template.findResources('AWS::Lambda::Function', {
      Properties: {
        Handler: 'index.handler',
        Runtime:  'nodejs18.x',
      },
    });
    const functionKeys = Object.keys(lambdas);
    expect(functionKeys.length).toBeGreaterThanOrEqual(1);

    // At least one Lambda has inline code containing the sunset date
    const anyHasSunsetDate = functionKeys.some(key => {
      const props = lambdas[key].Properties;
      const code  = props.Code || {};
      const zipFile: string = code.ZipFile || '';
      return zipFile.includes(STACK_PROPS.sunsetDate);
    });
    expect(anyHasSunsetDate).toBe(true);
  });

  test('Lambda@Edge handler code contains inbox-to-agent path mapping', () => {
    const lambdas = template.findResources('AWS::Lambda::Function', {
      Properties: {
        Handler: 'index.handler',
        Runtime:  'nodejs18.x',
      },
    });
    const anyHasMapping = Object.keys(lambdas).some(key => {
      const zipFile: string = lambdas[key].Properties.Code?.ZipFile || '';
      return zipFile.includes('/v1/inboxes') && zipFile.includes('/v1/agents');
    });
    expect(anyHasMapping).toBe(true);
  });

  test('Lambda@Edge handler code references the target API URL', () => {
    const lambdas = template.findResources('AWS::Lambda::Function', {
      Properties: {
        Handler: 'index.handler',
        Runtime:  'nodejs18.x',
      },
    });
    const anyHasTarget = Object.keys(lambdas).some(key => {
      const zipFile: string = lambdas[key].Properties.Code?.ZipFile || '';
      return zipFile.includes(STACK_PROPS.targetApiUrl);
    });
    expect(anyHasTarget).toBe(true);
  });

  // ── CloudFront ↔ Lambda edge association ────────────────────────────────

  test('CloudFront distribution associates the Lambda@Edge on viewer-request', () => {
    template.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultCacheBehavior: Match.objectLike({
          LambdaFunctionAssociations: Match.arrayWith([
            Match.objectLike({ EventType: 'viewer-request' }),
          ]),
        }),
      }),
    });
  });

  // ── ACM Certificate ─────────────────────────────────────────────────────

  test('creates an ACM certificate for api.victorymail.dev', () => {
    template.hasResourceProperties('AWS::CertificateManager::Certificate', {
      DomainName: 'api.victorymail.dev',
    });
  });

  // ── Route 53 ────────────────────────────────────────────────────────────

  test('creates a Route 53 A alias record pointing at the CloudFront distribution', () => {
    // CDK emits the CloudFront hosted zone ID as Fn::FindInMap, not a literal string,
    // so we match only on the record type and name.
    template.hasResourceProperties('AWS::Route53::RecordSet', {
      Type: 'A',
      Name: Match.stringLikeRegexp('api\\.victorymail\\.dev'),
      AliasTarget: Match.objectLike({
        DNSName: Match.objectLike({
          'Fn::GetAtt': Match.arrayWith(['SunsetDistributionE2DE3C25', 'DomainName']),
        }),
      }),
    });
  });
});
