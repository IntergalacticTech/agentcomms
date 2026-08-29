import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import Header from "../components/Header";

interface AgentRow {
  agent_id: string;
  name: string;
  email?: string;
  status?: string;
  created_at?: string;
}

interface ChannelRecord {
  channel?: string;
  details?: Record<string, string | undefined>;
  config?: Record<string, string | undefined>;
  status?: string;
}

interface AgentListResponse {
  agents?: AgentRow[];
  data?: AgentRow[];
}

interface ChannelsResponse {
  channels?: ChannelRecord[];
}

const PLATFORM_DOMAINS = ["agentcomms.dev"] as const;

function emailChannelDetails(channels: ChannelRecord[]): { email?: string; status?: string } {
  const email = channels.find((channel) => channel?.channel === "email");
  const details = email?.details || email?.config || {};
  return {
    email: details.address || details.email,
    status: email?.status,
  };
}

export default function InboxesPage() {
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newLocalPart, setNewLocalPart] = useState("");
  const [newDomain, setNewDomain] = useState<string>(PLATFORM_DOMAINS[0]);
  const [newName, setNewName] = useState("");

  async function load() {
    setError("");
    try {
      const resp = await api.get("/agents") as AgentListResponse;
      const baseAgents = resp?.agents || resp?.data || [];
      const rows = await Promise.all(
        baseAgents.map(async (agent) => {
          try {
            const channelsResp = await api.get(`/agents/${agent.agent_id}/channels`) as ChannelsResponse;
            return {
              ...agent,
              ...emailChannelDetails(channelsResp?.channels || []),
            };
          } catch {
            return agent;
          }
        })
      );
      setAgents(rows);
    } catch {
      setTimeout(async () => {
        try {
          const resp = await api.get("/agents") as AgentListResponse;
          setAgents(resp?.agents || resp?.data || []);
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Failed to load agents");
        }
      }, 1000);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const localPart = newLocalPart.trim().toLowerCase();
    if (!localPart) {
      setError("Email local part is required");
      return;
    }
    setCreating(true);
    setError("");
    try {
      await api.post("/agents", {
        name: newName.trim() || localPart,
        provision: {
          email: {
            local_part: localPart,
            domain: newDomain,
          },
        },
      });
      setShowCreate(false);
      setNewLocalPart("");
      setNewName("");
      setNewDomain(PLATFORM_DOMAINS[0]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create agent");
    } finally {
      setCreating(false);
    }
  }

  function statusBadge(status?: string) {
    const colors: Record<string, string> = {
      active: "bg-green-100 text-green-700",
      pending_verification: "bg-yellow-100 text-yellow-700",
      pending_oauth: "bg-yellow-100 text-yellow-700",
      disabled: "bg-red-100 text-red-700",
    };
    return (
      <span
        className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${colors[status || ""] || "bg-gray-100 text-gray-700"}`}
      >
        {status || "unknown"}
      </span>
    );
  }

  return (
    <>
      <Header title="Agents" />
      <div className="p-8">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm flex justify-between items-center">
            <span>{error}</span>
            <button
              onClick={() => void load()}
              className="ml-4 px-3 py-1 bg-red-100 text-red-700 text-xs font-medium rounded hover:bg-red-200"
            >
              Retry
            </button>
          </div>
        )}

        <div className="flex justify-between items-center mb-6">
          <p className="text-sm text-gray-500">
            {agents.length} agent{agents.length !== 1 ? "s" : ""}
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
          >
            Create Agent
          </button>
        </div>

        {showCreate && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">
              New Agent
            </h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="flex flex-wrap gap-4">
                <div className="flex-1 min-w-[200px]">
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Email local part
                  </label>
                  <input
                    type="text"
                    required
                    value={newLocalPart}
                    onChange={(e) => setNewLocalPart(e.target.value)}
                    placeholder="signup-bot"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div className="flex-1 min-w-[200px]">
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Domain
                  </label>
                  <select
                    value={newDomain}
                    onChange={(e) => setNewDomain(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {PLATFORM_DOMAINS.map((d) => (
                      <option key={d} value={d}>
                        @{d}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex-1 min-w-[200px]">
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="Signup Bot"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
              <p className="text-xs text-gray-500">
                Will create: <span className="font-mono">{newLocalPart.trim() || "local"}@{newDomain}</span>
              </p>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
                >
                  {creating ? "Creating..." : "Create"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2 text-gray-700 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Agent
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Email Channel
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Status
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Created
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {agents.map((agent) => (
                <tr key={agent.agent_id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <Link
                      to={`/agents/${agent.agent_id}`}
                      className="text-sm font-medium text-indigo-600 hover:text-indigo-700"
                    >
                      {agent.name || agent.agent_id}
                    </Link>
                    <p className="text-xs text-gray-400 font-mono mt-1">{agent.agent_id}</p>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-700 font-mono">
                    {agent.email || "--"}
                  </td>
                  <td className="px-6 py-4">{statusBadge(agent.status)}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {agent.created_at ? new Date(agent.created_at).toLocaleDateString() : "--"}
                  </td>
                </tr>
              ))}
              {agents.length === 0 && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-6 py-12 text-center text-sm text-gray-400"
                  >
                    No agents yet. Create one to get started.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
