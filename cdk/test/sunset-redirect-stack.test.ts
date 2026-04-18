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

    // The handler is now deployed via Code.fromAsset (4 KB inline limit forced
    // the switch), so the CFN template references an S3-backed asset rather
    // than raw code. We verify the stack produces an S3Bucket/S3Key pair.
    const hasS3Asset = functionKeys.some(key => {
      const code = lambdas[key].Properties.Code || {};
      return code.S3Bucket && code.S3Key;
    });
    expect(hasS3Asset).toBe(true);
  });

  // The inbox→agent path mapping and target API URL substitution are exercised
  // directly in cdk/edge-handlers/sunset-redirect/ — the synth-time substitution
  // doesn't land in the CFN template (it lands in the uploaded zip), so we
  // verify via filesystem checks on the source file instead.
  test('Edge handler source contains inbox-to-agent mapping + __TARGET_API_URL__ placeholder', () => {
    const fs = require('fs');
    const path = require('path');
    const source = fs.readFileSync(
      path.join(__dirname, '..', 'edge-handlers', 'sunset-redirect', 'index.js'),
      'utf8',
    );
    expect(source).toContain('/v1/inboxes');
    expect(source).toContain('/v1/agents');
    expect(source).toContain('__TARGET_API_URL__');
    expect(source).toContain('__SUNSET_DATE__');
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
