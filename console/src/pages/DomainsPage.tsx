import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import Header from "../components/Header";

interface DnsRecord {
  type: string;
  name: string;
  value: string;
}

interface Domain {
  domain_id: string;
  domain_name: string;
  status: string;
  dns_records?: Record<string, DnsRecord | DnsRecord[]>;
  created_at: string;
}

interface DomainsResponse {
  domains?: Domain[];
  data?: Domain[];
}

function flattenDnsRecords(records?: Domain["dns_records"]): DnsRecord[] {
  if (!records) return [];
  return Object.values(records).flatMap((record) => Array.isArray(record) ? record : [record]);
}

export default function DomainsPage() {
  const [domains, setDomains] = useState<Domain[]>([]);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newDomain, setNewDomain] = useState("");

  async function load() {
    setError("");
    try {
      const resp = await api.get("/domains") as DomainsResponse;
      setDomains(resp?.domains || resp?.data || []);
    } catch {
      setTimeout(async () => {
        try {
          const resp = await api.get("/domains") as DomainsResponse;
          setDomains(resp?.domains || resp?.data || []);
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Failed to load domains");
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
      await api.post("/domains", { domain_name: newDomain.trim().toLowerCase() });
      setShowCreate(false);
      setNewDomain("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add domain");
    } finally {
      setCreating(false);
    }
  }

  async function handleVerify(domainId: string) {
    try {
      await api.post(`/domains/${domainId}/verify`);
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Verification failed"
      );
    }
  }

  function statusBadge(status: string) {
    const colors: Record<string, string> = {
      verified: "bg-green-100 text-green-700",
      pending: "bg-yellow-100 text-yellow-700",
      pending_verification: "bg-yellow-100 text-yellow-700",
      failed: "bg-red-100 text-red-700",
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
      <Header title="Domains" />
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
            {domains.length} domain{domains.length !== 1 ? "s" : ""}
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
          >
            Add Domain
          </button>
        </div>

        {showCreate && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">
              Add Domain
            </h3>
            <form onSubmit={handleCreate} className="flex gap-4">
              <input
                type="text"
                required
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                placeholder="example.com"
                className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <button
                type="submit"
                disabled={creating}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
              >
                {creating ? "Adding..." : "Add"}
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

        <div className="space-y-4">
          {domains.map((domain) => {
            const records = flattenDnsRecords(domain.dns_records);
            return (
              <div
                key={domain.domain_id}
                className="bg-white rounded-lg shadow-sm border border-gray-200 p-6"
              >
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">
                      {domain.domain_name}
                    </h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Added {new Date(domain.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {statusBadge(domain.status)}
                    {domain.status !== "verified" && (
                      <button
                        onClick={() => handleVerify(domain.domain_id)}
                        className="text-sm text-indigo-600 hover:text-indigo-700 font-medium"
                      >
                        Verify
                      </button>
                    )}
                  </div>
                </div>
                {records.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase mb-2">
                      DNS Records to Configure
                    </p>
                    <div className="bg-gray-50 rounded-md overflow-hidden">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-gray-200">
                            <th className="text-left px-4 py-2 font-medium text-gray-500">
                              Type
                            </th>
                            <th className="text-left px-4 py-2 font-medium text-gray-500">
                              Name
                            </th>
                            <th className="text-left px-4 py-2 font-medium text-gray-500">
                              Value
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200">
                          {records.map((rec, i) => (
                            <tr key={`${rec.name}-${i}`}>
                              <td className="px-4 py-2 font-mono text-gray-700">
                                {rec.type}
                              </td>
                              <td className="px-4 py-2 font-mono text-gray-700 break-all">
                                {rec.name}
                              </td>
                              <td className="px-4 py-2 font-mono text-gray-700 break-all">
                                {rec.value}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {domains.length === 0 && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center text-sm text-gray-400">
              No custom domains configured.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
