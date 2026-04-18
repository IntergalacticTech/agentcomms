// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

// cdk/lib/stacks/sunset-redirect-stack.ts
//
// Sunset-redirect stack for api.victorymail.dev.
//
// Creates:
//   - ACM cert in us-east-1 for api.victorymail.dev (CloudFront requires us-east-1)
//   - Lambda@Edge (viewer-request) that:
//       • Maps old /v1/inboxes/* paths to /v1/agents/* with prefix rewrite
//       • Returns 301 to https://api.agentcomms.dev{new_path} for mapped paths
//       • Returns 410 Gone after SUNSET_DATE (or for unmapped/retired paths)
//       • Adds Sunset + Deprecation headers on every response
//   - CloudFront distribution fronting api.victorymail.dev
//   - Route 53 alias A record → CloudFront distribution
//
// IMPORTANT: Do NOT deploy before DNS is ready. See docs/runbooks/pivot-cutover.md.
//
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import {
  Distribution,
  ViewerProtocolPolicy,
  AllowedMethods,
  CachePolicy,
  OriginRequestPolicy,
  LambdaEdgeEventType,
  experimental,
} from 'aws-cdk-lib/aws-cloudfront';
import { HttpOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';
import {
  Certificate,
  CertificateValidation,
  ICertificate,
} from 'aws-cdk-lib/aws-certificatemanager';
import {
  HostedZone,
  ARecord,
  RecordTarget,
} from 'aws-cdk-lib/aws-route53';
import { CloudFrontTarget } from 'aws-cdk-lib/aws-route53-targets';
import { Runtime, Code } from 'aws-cdk-lib/aws-lambda';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

export interface SunsetRedirectStackProps extends StackProps {
  /** e.g. "https://api.agentcomms.dev" — no trailing slash */
  targetApiUrl: string;
  /** ISO 8601 date string; after this date, all requests return 410 Gone */
  sunsetDate: string;
  /** Route 53 hosted zone ID for victorymail.dev */
  hostedZoneId: string;
  /** e.g. "api.victorymail.dev" */
  legacyHostname: string;
  /** Optional: pre-existing ACM cert ARN in us-east-1. If omitted, a new cert is created. */
  acmCertArn?: string;
}

// ---------------------------------------------------------------------------
// Lambda@Edge handler code (inlined as a string; deployed as a Node.js 18 fn)
// ---------------------------------------------------------------------------
//
// Mapping rules (matches spec §6.5):
//
//   /v1/inboxes                          → /v1/agents                (list)
//   /v1/inboxes/{inb_id}                 → /v1/agents/agt_{id[4:]}   (detail)
//   /v1/inboxes/{inb_id}/messages        → /v1/agents/agt_{id[4:]}/messages
//   /v1/inboxes/{inb_id}/messages/{m}    → /v1/agents/agt_{id[4:]}/messages/{m}
//   /v1/inboxes/{inb_id}/send            → /v1/agents/agt_{id[4:]}/messages  (POST)
//   /v1/inboxes/{inb_id}/wait            → /v1/agents/agt_{id[4:]}/wait
//   /v1/inboxes/{inb_id}/extract-otp     → /v1/agents/agt_{id[4:]}/extract-otp
//   /v1/inboxes/{inb_id}/webhooks        → /v1/agents/agt_{id[4:]}/webhooks
//   /v1/inboxes/{inb_id}/threads         → /v1/agents/agt_{id[4:]}/threads
//   /v1/inboxes/{inb_id}/drafts          → /v1/agents/agt_{id[4:]}/drafts
//   /v1/pods, /v1/pods/{id}              → 410 (retired)
//   /v1/domains                          → /v1/domains (passthrough)
//   /v1/ai/*                             → 410 (now agent-scoped)
//   /v1/openapi.json                     → /v1/openapi.json (passthrough)
//   anything else                        → 410 generic

function buildEdgeHandlerCode(targetApiUrl: string, sunsetDate: string): string {
  return `
'use strict';

// Injected at synth time by CDK
const TARGET_API_URL = ${JSON.stringify(targetApiUrl)};
const SUNSET_DATE    = ${JSON.stringify(sunsetDate)};

// ---------------------------------------------------------------------------
// Path-mapping helpers
// ---------------------------------------------------------------------------

/**
 * Given a legacy /v1/... path, return { redirect: <new_path> } or
 * { gone: <reason> } or { passthrough: true }.
 */
function mapPath(path, method) {
  // Normalise: strip trailing slash except root
  const p = path.endsWith('/') && path.length > 1 ? path.slice(0, -1) : path;

  // Passthrough: openapi spec
  if (p === '/v1/openapi.json') return { passthrough: true };

  // Passthrough: domains (org-scoped, unchanged)
  if (p === '/v1/domains' || p.startsWith('/v1/domains/')) return { passthrough: true };

  // Retired: pods
  if (p === '/v1/pods' || p.startsWith('/v1/pods/')) {
    return { gone: 'The /v1/pods endpoint has been retired and has no equivalent in AgentComms. See https://docs.agentcomms.dev/migration for details.' };
  }

  // Retired: top-level AI (now agent-scoped)
  if (p === '/v1/ai' || p.startsWith('/v1/ai/')) {
    return { gone: 'AI endpoints are now scoped to agents. Use /v1/agents/{agent_id}/ai/* instead. See https://docs.agentcomms.dev/migration.' };
  }

  // /v1/inboxes (list)
  if (p === '/v1/inboxes') return { redirect: '/v1/agents' };

  // /v1/inboxes/{inb_id}[/sub-resource[/...]]
  const inboxMatch = p.match(/^\\/v1\\/inboxes\\/(inb_[^/]+)(\\/.+)?$/);
  if (inboxMatch) {
    const inbId  = inboxMatch[1];  // e.g. inb_abc123
    const suffix = inboxMatch[2] || ''; // e.g. /messages or /messages/msg_xyz

    // Strip "inb_" prefix → "agt_" prefix
    const rawId  = inbId.slice(4); // drop "inb_"
    const agtId  = 'agt_' + rawId;
    const base   = '/v1/agents/' + agtId;

    // /v1/inboxes/{id}/send → POST to /v1/agents/{id}/messages
    if (suffix === '/send') return { redirect: base + '/messages' };

    // All other sub-resources map verbatim
    return { redirect: base + suffix };
  }

  // Default: 410 for anything else under /v1/
  return { gone: 'This endpoint does not exist in AgentComms. See https://docs.agentcomms.dev/migration for the full endpoint mapping.' };
}

// ---------------------------------------------------------------------------
// Build a synthetic CloudFront response object
// ---------------------------------------------------------------------------

function response(statusCode, body, extraHeaders) {
  const headers = Object.assign({
    'content-type': [{ key: 'Content-Type', value: 'application/json' }],
    'sunset':       [{ key: 'Sunset', value: SUNSET_DATE }],
    'deprecation':  [{ key: 'Deprecation', value: 'true' }],
    'link':         [{ key: 'Link', value: '<https://docs.agentcomms.dev/migration>; rel="deprecation"' }],
  }, extraHeaders || {});
  return {
    status: String(statusCode),
    statusDescription: statusCode === 301 ? 'Moved Permanently' : 'Gone',
    headers,
    body: JSON.stringify(body),
  };
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

exports.handler = async function(event) {
  const request = event.Records[0].cf.request;
  const path    = request.uri;
  const method  = (request.method || 'GET').toUpperCase();

  // After sunset date, everything returns 410
  const now        = new Date();
  const sunsetTime = new Date(SUNSET_DATE);
  if (now >= sunsetTime) {
    return response(410, {
      error:   'gone',
      message: 'api.victorymail.dev has been permanently decommissioned. ' +
               'Please migrate to api.agentcomms.dev. See https://docs.agentcomms.dev/migration.',
      sunset:  SUNSET_DATE,
    });
  }

  // Always add sunset/deprecation headers on pass-through responses too.
  const result = mapPath(path, method);

  if (result.gone) {
    return response(410, {
      error:   'gone',
      message: result.gone,
      sunset:  SUNSET_DATE,
    });
  }

  if (result.redirect) {
    const newLocation = TARGET_API_URL + result.redirect;
    // Preserve query string
    const qs = request.querystring ? '?' + request.querystring : '';
    return response(301, {
      message:  'This endpoint has moved.',
      location: newLocation + qs,
    }, {
      location: [{ key: 'Location', value: newLocation + qs }],
    });
  }

  // passthrough: let CloudFront forward to origin (api.victorymail.dev original API GW)
  // but inject deprecation headers into the request so origin can see them too
  request.headers['x-sunset']      = [{ key: 'X-Sunset',      value: SUNSET_DATE }];
  request.headers['x-deprecation'] = [{ key: 'X-Deprecation', value: 'true' }];
  return request;
};
`;
}

// ---------------------------------------------------------------------------
// Stack
// ---------------------------------------------------------------------------

export class SunsetRedirectStack extends Stack {
  public readonly distribution: Distribution;

  constructor(scope: Construct, id: string, props: SunsetRedirectStackProps) {
    // Lambda@Edge functions MUST be in us-east-1
    super(scope, id, { ...props, env: { region: 'us-east-1', account: props.env?.account } });

    // ── ACM Certificate ──
    const hostedZone = HostedZone.fromHostedZoneAttributes(this, 'LegacyZone', {
      hostedZoneId: props.hostedZoneId,
      zoneName:     'victorymail.dev',
    });

    let cert: ICertificate;
    if (props.acmCertArn) {
      cert = Certificate.fromCertificateArn(this, 'ImportedCert', props.acmCertArn);
    } else {
      cert = new Certificate(this, 'LegacyCert', {
        domainName: props.legacyHostname,
        validation: CertificateValidation.fromDns(hostedZone),
      });
    }

    // ── Lambda@Edge ──
    //
    // We cannot use Code.fromInline (4 KB limit, and our handler with template-substituted
    // values is ~4.5 KB). We also can't use Lambda env vars (unsupported on Edge). So we
    // substitute the values into the handler source at synth time and deploy via
    // Code.fromAsset from a temporary directory.
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sunset-redirect-'));
    const sourcePath = path.join(__dirname, '..', '..', 'edge-handlers', 'sunset-redirect', 'index.js');
    const handlerSource = fs.readFileSync(sourcePath, 'utf8')
      .replace(/__TARGET_API_URL__/g, props.targetApiUrl)
      .replace(/__SUNSET_DATE__/g, props.sunsetDate);
    fs.writeFileSync(path.join(tmpDir, 'index.js'), handlerSource);

    const edgeFn = new experimental.EdgeFunction(this, 'SunsetRedirectFn', {
      runtime: Runtime.NODEJS_18_X,
      handler: 'index.handler',
      code:    Code.fromAsset(tmpDir),
      description: `Sunset redirect: api.victorymail.dev → api.agentcomms.dev (sunset: ${props.sunsetDate})`,
    });

    // ── CloudFront Distribution ──
    // Origin: the old victorymail API GW (receives only passthrough requests, i.e. /v1/domains etc.)
    // Most traffic never reaches the origin — the Lambda@Edge returns synthetic 301/410 responses.
    const origin = new HttpOrigin(props.legacyHostname, {
      httpsPort: 443,
      protocolPolicy: undefined, // defaults to HTTPS
    });

    this.distribution = new Distribution(this, 'SunsetDistribution', {
      defaultBehavior: {
        origin,
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: AllowedMethods.ALLOW_ALL,
        cachePolicy: CachePolicy.CACHING_DISABLED,       // never cache redirects / errors
        originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        edgeLambdas: [
          {
            functionVersion: edgeFn.currentVersion,
            eventType: LambdaEdgeEventType.VIEWER_REQUEST,
          },
        ],
      },
      domainNames: [props.legacyHostname],
      certificate: cert,
      comment: `Sunset redirect for ${props.legacyHostname} — decommissions on ${props.sunsetDate}`,
    });

    // ── Route 53 Alias A Record ──
    new ARecord(this, 'LegacyApiAliasRecord', {
      zone:       hostedZone,
      recordName: props.legacyHostname,
      target:     RecordTarget.fromAlias(new CloudFrontTarget(this.distribution)),
      ttl:        Duration.seconds(60),
      comment:    'Points legacy api.victorymail.dev at sunset-redirect CloudFront distribution',
    });
  }
}
