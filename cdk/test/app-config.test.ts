import { readFileSync } from 'fs';
import { join } from 'path';

describe('CDK app configuration', () => {
  test('does not pin AgentComms deployment to the legacy production account', () => {
    const appSource = readFileSync(join(__dirname, '..', 'bin', 'app.ts'), 'utf8');
    expect(appSource).not.toContain('732770059798');
  });

  test('defaults the app entrypoint to AgentComms-only deployment', () => {
    const appSource = readFileSync(join(__dirname, '..', 'bin', 'app.ts'), 'utf8');
    expect(appSource).toContain('const deployLegacy = flag("deployLegacy", false)');
    expect(appSource).toContain('const deployAgentComms = flag("deployAgentComms", true)');
  });
});
