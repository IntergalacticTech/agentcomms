# AgentComms Console

React + TypeScript + Vite developer console for AgentComms.

The console is the browser surface for managing:

- Agents
- Channels
- Messages
- API keys
- Custom domains
- Organization settings

## Development

```bash
npm install
npm run dev
```

Set `VITE_AGENTCOMMS_API_BASE` when pointing the console at a self-hosted API:

```bash
VITE_AGENTCOMMS_API_BASE=https://api.your-domain.com/v1 npm run dev
```

## Validation

```bash
npm run lint
npm run build
```

## Deployment

The current production workflow builds this package. Public static-site deployment for the marketing surface is handled by the `AgentCommsLanding` CDK stack. A future AgentComms console stack should be wired only after the console auth routes are part of the AgentComms API stack.
