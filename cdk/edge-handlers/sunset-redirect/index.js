'use strict';
// SPDX-License-Identifier: Apache-2.0
// Lambda@Edge viewer-request handler for api.victorymail.dev → api.agentcomms.dev.
// Values __TARGET_API_URL__ and __SUNSET_DATE__ are replaced at CDK bundling time.

const TARGET_API_URL = '__TARGET_API_URL__';
const SUNSET_DATE    = '__SUNSET_DATE__';

function mapPath(path, method) {
  const p = path.endsWith('/') && path.length > 1 ? path.slice(0, -1) : path;
  if (p === '/v1/openapi.json') return { passthrough: true };
  if (p === '/v1/domains' || p.startsWith('/v1/domains/')) return { passthrough: true };
  if (p === '/v1/pods' || p.startsWith('/v1/pods/')) {
    return { gone: 'The /v1/pods endpoint has been retired and has no equivalent in AgentComms.' };
  }
  if (p === '/v1/ai' || p.startsWith('/v1/ai/')) {
    return { gone: 'AI endpoints are now scoped to agents. Use /v1/agents/{agent_id}/ai/*.' };
  }
  if (p === '/v1/inboxes') return { redirect: '/v1/agents' };
  const inboxMatch = p.match(/^\/v1\/inboxes\/(inb_[^/]+)(\/.+)?$/);
  if (inboxMatch) {
    const rawId = inboxMatch[1].slice(4);
    const base  = '/v1/agents/agt_' + rawId;
    const suffix = inboxMatch[2] || '';
    if (suffix === '/send') return { redirect: base + '/messages' };
    return { redirect: base + suffix };
  }
  return { gone: 'This endpoint does not exist in AgentComms. See https://docs.agentcomms.dev/migration.' };
}

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

exports.handler = async function(event) {
  const request = event.Records[0].cf.request;
  const path    = request.uri;
  const method  = (request.method || 'GET').toUpperCase();

  if (new Date() >= new Date(SUNSET_DATE)) {
    return response(410, {
      error:   'gone',
      message: 'api.victorymail.dev has been permanently decommissioned. Please migrate to api.agentcomms.dev.',
      sunset:  SUNSET_DATE,
    });
  }

  const result = mapPath(path, method);
  if (result.gone) {
    return response(410, { error: 'gone', message: result.gone, sunset: SUNSET_DATE });
  }
  if (result.redirect) {
    const qs = request.querystring ? '?' + request.querystring : '';
    const newLocation = TARGET_API_URL + result.redirect + qs;
    return response(301, { message: 'This endpoint has moved.', location: newLocation }, {
      location: [{ key: 'Location', value: newLocation }],
    });
  }
  request.headers['x-sunset']      = [{ key: 'X-Sunset',      value: SUNSET_DATE }];
  request.headers['x-deprecation'] = [{ key: 'X-Deprecation', value: 'true' }];
  return request;
};
