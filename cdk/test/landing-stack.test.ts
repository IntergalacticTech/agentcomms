// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.

import { App } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { LandingStack } from '../lib/stacks/landing-stack';

describe('LandingStack', () => {
  test('uses an AgentComms bucket prefix when requested', () => {
    const app = new App();
    const stack = new LandingStack(app, 'AgentCommsLandingTest', {
      stage: 'prod',
      siteId: 'agentcomms',
    });
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketName: Match.objectLike({
        'Fn::Join': Match.arrayWith([
          '',
          Match.arrayWith([Match.stringLikeRegexp('^agentcomms-landing-')]),
        ]),
      }),
    });
  });

  test('keeps the legacy bucket prefix by default', () => {
    const app = new App();
    const stack = new LandingStack(app, 'LegacyLandingTest', { stage: 'dev' });
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketName: Match.objectLike({
        'Fn::Join': Match.arrayWith([
          '',
          Match.arrayWith([Match.stringLikeRegexp('^victorymail-landing-')]),
        ]),
      }),
    });
  });
});
