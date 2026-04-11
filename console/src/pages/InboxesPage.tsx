import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import Header from "../components/Header";

interface Inbox {
  id: string;
  email: string;
  display_name: string;
  status: string;
  message_count?: number;
  created_at: string;
}

export default function InboxesPage() {
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newPrefix, setNewPrefix] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");

  function load() {
    setError("");
    api
      .get("/inboxes")
      .then((resp: any) => setInboxes(resp?.data || []))
      .catch(() => {
        setTimeout(() => {
          api
            .get("/inboxes")
            .then((resp: any) => setInboxes(resp?.data || []))
            .catch((e2) => setError(e2.message));
        }, 1000);
      });
  }

  useEffect(load, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      await api.post("/inboxes", {
        display_name: newDisplayName || newPrefix,
        prefix: newPrefix,
      });
      setShowCreate(false);
      setNewPrefix("");
      setNewDisplayName("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create inbox");
    } finally {
      setCreating(false);
    }
  }

  function statusBadge(status: string) {
    const colors: Record<string, string> = {
      active: "bg-green-100 text-green-700",
      pending: "bg-yellow-100 text-yellow-700",
      disabled: "bg-red-100 text-red-700",
    };
    return (
      <span
        className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${colors[status] || "bg-gray-100 text-gray-700"}`}
      >
        {status}
      </span>
    );
  }

  return (
    <>
      <Header title="Inboxes" />
      <div className="p-8">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm flex justify-between items-center">
            <span>{error}</span>
            <button
              onClick={load}
              className="ml-4 px-3 py-1 bg-red-100 text-red-700 text-xs font-medium rounded hover:bg-red-200"
            >
              Retry
            </button>
          </div>
        )}

        <div className="flex justify-between items-center mb-6">
          <p className="text-sm text-gray-500">
            {inboxes.length} inbox{inboxes.length !== 1 ? "es" : ""}
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
          >
            Create Inbox
          </button>
        </div>

        {showCreate && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">
              New Inbox
            </h3>
            <form onSubmit={handleCreate} className="flex flex-wrap gap-4">
              <input
                type="text"
                required
                value={newPrefix}
                onChange={(e) => setNewPrefix(e.target.value)}
                placeholder="Email prefix (e.g. support)"
                className="flex-1 min-w-[200px] px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <input
                type="text"
                value={newDisplayName}
                onChange={(e) => setNewDisplayName(e.target.value)}
                placeholder="Display name (optional)"
                className="flex-1 min-w-[200px] px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
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
                  Email
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Display Name
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-6 py-3">
                  Messages
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
              {inboxes.map((inbox) => (
                <tr key={inbox.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <Link
                      to={`/inboxes/${inbox.id}`}
                      className="text-sm font-medium text-indigo-600 hover:text-indigo-700"
                    >
                      {inbox.email}
                    </Link>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-700">
                    {inbox.display_name || "--"}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-700">
                    {inbox.message_count ?? "--"}
                  </td>
                  <td className="px-6 py-4">{statusBadge(inbox.status)}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {new Date(inbox.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
              {inboxes.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-6 py-12 text-center text-sm text-gray-400"
                  >
                    No inboxes yet. Create one to get started.
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
