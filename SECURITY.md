# Security Policy

## Supported versions

We apply security fixes to the `main` branch only. There are no versioned backport branches at this time.

## Reporting a vulnerability

Please do NOT open a public GitHub issue for security vulnerabilities.

**Email:** `security@agentcomms.dev`

We respond to all reports within 48 hours. Please include:
- A description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept code if applicable)
- Any suggested mitigations

We follow coordinated disclosure: we ask that you give us a reasonable window (typically 90 days) to patch before public disclosure. We'll keep you informed of progress and credit you in the release notes unless you prefer anonymity.

## Scope

In scope:
- Authentication and authorization bugs in the Hub API (`lambdas/authorizer/`)
- API key exposure or leakage
- Injection vulnerabilities in Lambda handlers
- Insecure AWS resource configurations in CDK stacks
- Secrets management issues (SSM Parameter Store, Secrets Manager)

Out of scope:
- Denial-of-service against self-hosted deployments (you control your own AWS account)
- Issues in third-party dependencies (report to upstream)
- Social engineering

## Disclosure

We follow a 90-day coordinated disclosure timeline. Critical vulnerabilities may be patched faster. We will publish a CVE or security advisory for vulnerabilities with a CVSS score of 7.0 or higher.
