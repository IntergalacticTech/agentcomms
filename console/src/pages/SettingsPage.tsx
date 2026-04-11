import { useEffect, useState } from "react";
import { api } from "../api/client";
import Header from "../components/Header";

interface OrgInfo {
  org_id: string;
  name: string;
  email: string;
  tier: string;
  quota?: {
    inboxes: number;
    messages_per_day: number;
    api_keys: number;
  };
  usage?: {
    inboxes: number;
    messages_today: number;
    api_keys: number;
  };
}

function QuotaBar({
  label,
  used,
  total,
}: {
  label: string;
  used: number;
  total: number;
}) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;
  const color = pct > 90 ? "bg-red-500" : pct > 70 ? "bg-yellow-500" : "bg-indigo-600";

  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-700">{label}</span>
        <span className="text-gray-500">
          {used} / {total}
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`h-2 rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get("/organizations/me")
      .then(setOrg)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <Header title="Settings" />
      <div className="p-8">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm">
            {error}
          </div>
        )}

        {org && (
          <div className="max-w-2xl space-y-6">
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h2 className="text-sm font-semibold text-gray-900 mb-4">
                Organization
              </h2>
              <div className="grid grid-cols-[auto,1fr] gap-x-6 gap-y-3 text-sm">
                <span className="text-gray-500">Name</span>
                <span className="text-gray-900 font-medium">{org.name}</span>
                <span className="text-gray-500">Email</span>
                <span className="text-gray-900">{org.email}</span>
                <span className="text-gray-500">Org ID</span>
                <span className="text-gray-900 font-mono text-xs">
                  {org.org_id}
                </span>
                <span className="text-gray-500">Tier</span>
                <span>
                  <span className="inline-block px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-100 text-indigo-700">
                    {org.tier || "free"}
                  </span>
                </span>
              </div>
            </div>

            {org.quota && org.usage && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-sm font-semibold text-gray-900 mb-4">
                  Usage & Quotas
                </h2>
                <div className="space-y-4">
                  <QuotaBar
                    label="Inboxes"
                    used={org.usage.inboxes}
                    total={org.quota.inboxes}
                  />
                  <QuotaBar
                    label="Messages Today"
                    used={org.usage.messages_today}
                    total={org.quota.messages_per_day}
                  />
                  <QuotaBar
                    label="API Keys"
                    used={org.usage.api_keys}
                    total={org.quota.api_keys}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {!org && !error && (
          <div className="text-gray-400 text-sm">Loading...</div>
        )}
      </div>
    </>
  );
}
