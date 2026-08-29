# BYOC Implementation Plan

This document is obsolete.

The earlier BYOC plan depended on opaque Lambda container images, a license verification service, and Marketplace-gated deployments. That is no longer the product direction.

AgentComms is Apache-2.0 open source. Bring-your-own-cloud now means cloning the repository and deploying the CDK stacks into your AWS account with `agentcomms bootstrap`.

Current docs:

- [byoc.md](./byoc.md) - self-hosting model
- [AGENT.md](../AGENT.md) - coding-agent deployment contract
- [architecture.md](./architecture.md) - current system architecture
- [adapter-roadmap.md](./adapter-roadmap.md) - channel adapter roadmap
