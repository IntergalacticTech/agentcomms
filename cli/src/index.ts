#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
import { Command } from "commander";
import { bootstrapCommand } from "./commands/bootstrap.js";
import { doctorCommand } from "./commands/doctor.js";
import { statusCommand } from "./commands/status.js";
import { channelsCommand } from "./commands/channels.js";
import { keysCommand } from "./commands/keys.js";
import { agentsCommand } from "./commands/agents.js";
import { destroyCommand } from "./commands/destroy.js";
import { versionCommand } from "./commands/version.js";

const program = new Command();
program
  .name("agentcomms")
  .description("Deploy and operate AgentComms in your AWS account")
  .version("0.1.0");

program.addCommand(bootstrapCommand());
program.addCommand(doctorCommand());
program.addCommand(statusCommand());
program.addCommand(channelsCommand());
program.addCommand(keysCommand());
program.addCommand(agentsCommand());
program.addCommand(destroyCommand());
program.addCommand(versionCommand());

program.parseAsync(process.argv).catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
