// SPDX-License-Identifier: Apache-2.0
import { buildBootstrapStacks } from "../commands/bootstrap.js";

describe("bootstrap stack selection", () => {
  it("deploys data, API, wrapper, and concrete adapter stacks by default", () => {
    expect(buildBootstrapStacks("")).toEqual([
      "AgentCommsData",
      "AgentCommsEvents",
      "AgentCommsApi",
      "AgentCommsAdapters",
      "AgentCommsAdapters-Email",
      "AgentCommsAdapters-Sms",
      "AgentCommsAdapters-Push",
      "AgentCommsAdapters-Slack",
      "AgentCommsAdapters-Telegram",
    ]);
  });

  it("keeps email and omits skipped optional channel adapter stacks", () => {
    expect(buildBootstrapStacks("sms, slack")).toEqual([
      "AgentCommsData",
      "AgentCommsEvents",
      "AgentCommsApi",
      "AgentCommsAdapters",
      "AgentCommsAdapters-Email",
      "AgentCommsAdapters-Push",
      "AgentCommsAdapters-Telegram",
    ]);
  });
});
