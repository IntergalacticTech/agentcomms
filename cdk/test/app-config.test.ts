import { readFileSync } from 'fs';
import { join } from 'path';

describe('CDK app configuration', () => {
  test('does not pin AgentComms deployment to the legacy production account', () => {
    const appSource = readFileSync(join(__dirname, '..', 'bin', 'app.ts'), 'utf8');
    const legacyAccountId = '732770' + '059798';
    expect(appSource).not.toContain(legacyAccountId);
  });

  test('defaults the app entrypoint to AgentComms-only deployment', () => {
    const appSource = readFileSync(join(__dirname, '..', 'bin', 'app.ts'), 'utf8');
    expect(appSource).toContain('const deployLegacy = flag("deployLegacy", false)');
    expect(appSource).toContain('const deployAgentComms = flag("deployAgentComms", true)');
  });

  test('includes the public landing site in AgentComms production deploys', () => {
    const appSource = readFileSync(join(__dirname, '..', 'bin', 'app.ts'), 'utf8');
    expect(appSource).toContain('new LandingStack(app, "AgentCommsLanding"');
    expect(appSource).toContain('siteId: "agentcomms"');
  });
});
