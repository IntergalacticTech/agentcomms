import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import Header from "../components/Header";

interface ApiKey {
  key_id: string;
  name?: string;
  key_prefix?: string;
  scope: "org" | "agent" | "channel" | string;
  agent_id?: string | null;
  channel_id?: string | null;
  revoked?: boolean;
  created_at: string;
  last_used_at?: string | null;
}

interface ApiKeysResponse {
  api_keys?: ApiKey[];
  data?: ApiKey[];
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newScope, setNewScope] = useState<ApiKey["scope"]>("org");
  const [newAgentId, setNewAgentId] = useState("");
  const [newChannelId, setNewChannelId] = useState("");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [copied, setCopied] = useState(false);

  async function load() {
    setError("");
    try {
      const resp = await api.get("/api-keys") as ApiKeysResponse;
      setKeys(resp?.api_keys || resp?.data || []);
    } catch {
      setTimeout(async () => {
        try {
          const resp = await api.get("/api-keys") as ApiKeysResponse;
          setKeys(resp?.api_keys || resp?.data || []);
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Failed to load API keys");
        }
      }, 1000);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const body: Record<string, string> = {
        name: newName.trim(),
        scope: newScope,
      };
      if (newScope === "agent" || newScope === "channel") {
        body.agent_id = newAgentId.trim();
      }
      if (newScope === "channel") {
        body.channel_id = newChannelId.trim();
      }
      const data = await api.post("/api-keys", body) as ApiKey & { key?: string };
      setNewKeyValue(data.key || "");
      setNewName("");
      setNewAgentId("");
      setNewChannelId("");
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create API key"
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(keyId: string) {
    if (!confirm("Revoke this API key? This cannot be undone.")) return;
    try {
      await api.delete(`/api-keys/${keyId}`);
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to revoke API key"
      );
    }
  }

  function copyKey() {
    navigator.clipboard.writeText(newKeyValue);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <>
      <Header title="API Keys" />
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

        {newKeyValue && (
          <div className="mb-6 bg-white rounded-lg shadow-sm border border-green-200 p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">
              New API Key Created
            </h3>
            <p className="text-xs text-gray-500 mb-3">
              Copy this key now. You will not be able to see it again.
            </p>
            <div className="bg-gray-900 rounded-md p-4 mb-3">
              <code className="text-green-400 text-sm break-all">
                {newKeyValue}
              </code>
            </div>
            <div className="flex gap-2">
              <button
                onClick={copyKey}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
              >
                {copied ? "Copied!" : "Copy"}
              </button>
              <button
                onClick={() => {
                  setNewKeyValue("");
                  setShowCreate(false);
                }}
                className="px-4 py-2 text-gray-700 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
              >
                Done
              </button>
            </div>
          </div>
        )}

        <div className="flex justify-between items-center mb-6">
          <p className="text-sm text-gray-500">
            {keys.length} key{keys.length !== 1 ? "s" : ""}
          </p>
          {!showCreate && !newKeyValue && (
            <button
              onClick={() => setShowCreate(true)}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
            >
              Create API Key
            </button>
          )}
        </div>

        {showCreate && !newKeyValue && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">
              New API Key
            </h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="flex flex-wrap gap-4 items-end">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    required
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="invoice-agent"
                    className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Scope
                  </label>
                  <select
                    value={newScope}
                    onChange={(e) => setNewScope(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="org">Organization</option>
                    <option value="agent">Agent</option>
                    <option value="channel">Channel</option>
                  </select>
                </div>
                {(newScope === "agent" || newScope === "channel") && (
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Agent ID
                    </label>
                    <input
                      type="text"
                      required
                      value={newAgentId}
                      onChange={(e) => setNewAgentId(e.target.value)}
                      placeholder="agt_..."
                      className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                )}
                {newScope === "channel" && (
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Channel ID
                    </label>
                    <input
                      type="text"
                      required
                      value={newChannelId}
                      onChange={(e) => setNewChannelId(e.target.value)}
                      placeholder="chan_..."
                      className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                )}
              </div>
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
                  Name
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Key
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Scope
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Created
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Last Used
                </th>
                <th className="text-right text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {keys.map((key) => (
                <tr key={key.key_id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 text-sm text-gray-700">
                    {key.name || "--"}
                  </td>
                  <td className="px-6 py-4 text-sm font-mono text-gray-700">
                    {key.key_prefix || "--"}...
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-block px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-700">
                      {key.scope}
                    </span>
                    {key.agent_id && (
                      <p className="text-xs text-gray-400 font-mono mt-1">{key.agent_id}</p>
                    )}
                    {key.channel_id && (
                      <p className="text-xs text-gray-400 font-mono">{key.channel_id}</p>
                    )}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {new Date(key.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {key.last_used_at
                      ? new Date(key.last_used_at).toLocaleDateString()
                      : "Never"}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => handleDelete(key.key_id)}
                      disabled={key.revoked}
                      className="text-sm text-red-600 hover:text-red-700 font-medium disabled:text-gray-300"
                    >
                      {key.revoked ? "Revoked" : "Revoke"}
                    </button>
                  </td>
                </tr>
              ))}
              {keys.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-6 py-12 text-center text-sm text-gray-400"
                  >
                    No API keys. Create one to start using the API.
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
