import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import Header from "../components/Header";

interface ApiKey {
  key_id: string;
  prefix: string;
  scope: string;
  created_at: string;
  last_used_at?: string;
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newScope, setNewScope] = useState("full");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [copied, setCopied] = useState(false);

  function load() {
    api
      .get("/api-keys")
      .then((data) => setKeys(data.api_keys || data || []))
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const data = await api.post("/api-keys", { scope: newScope });
      setNewKeyValue(data.api_key || data.key);
      load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create API key"
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(keyId: string) {
    if (!confirm("Delete this API key? This cannot be undone.")) return;
    try {
      await api.delete(`/api-keys/${keyId}`);
      load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to delete API key"
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
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm">
            {error}
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
            <form onSubmit={handleCreate} className="flex gap-4 items-end">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Scope
                </label>
                <select
                  value={newScope}
                  onChange={(e) => setNewScope(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="full">Full Access</option>
                  <option value="read">Read Only</option>
                  <option value="send">Send Only</option>
                </select>
              </div>
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
            </form>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
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
                  <td className="px-6 py-4 text-sm font-mono text-gray-700">
                    {key.prefix}...
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-block px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-700">
                      {key.scope}
                    </span>
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
                      className="text-sm text-red-600 hover:text-red-700 font-medium"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {keys.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
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
