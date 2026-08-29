import { useEffect, useState } from "react";
import { api } from "../api/client";
import Header from "../components/Header";

type Tier = "free" | "starter" | "pro" | "enterprise";

interface Quotas {
  max_inboxes?: number;
  max_messages_per_day?: number;
  max_api_keys?: number;
  max_pods?: number;
  max_domains?: number;
  max_webhooks?: number;
  max_storage_mb?: number;
  retention_days?: number;
  ai_calls_per_month?: number;
}

interface Usage {
  inboxes?: number;
  pods?: number;
  api_keys?: number;
  domains?: number;
  webhooks?: number;
}

interface OrgInfo {
  id: string;
  name: string;
  email: string;
  tier: Tier;
  status: string;
  quotas?: Quotas;
  usage?: Usage;
}

const TIER_LABELS: Record<Tier, { label: string; price: string; color: string }> = {
  free: { label: "Free", price: "$0/mo", color: "bg-gray-100 text-gray-700" },
  starter: { label: "Starter", price: "$5/mo", color: "bg-indigo-100 text-indigo-700" },
  pro: { label: "Pro", price: "$25/mo", color: "bg-purple-100 text-purple-700" },
  enterprise: { label: "Enterprise", price: "Custom", color: "bg-amber-100 text-amber-800" },
};

function QuotaBar({
  label,
  used,
  total,
}: {
  label: string;
  used: number;
  total: number;
}) {
  // -1 sentinel means unlimited; render as ∞ with a flat green bar.
  const unlimited = total < 0;
  const pct = unlimited
    ? 100
    : total > 0
    ? Math.min((used / total) * 100, 100)
    : 100;
  const color = unlimited
    ? "bg-emerald-500"
    : total === 0
    ? "bg-gray-300"
    : pct > 90
    ? "bg-red-500"
    : pct > 70
    ? "bg-yellow-500"
    : "bg-indigo-600";

  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-700">{label}</span>
        <span className="text-gray-500">
          {used} / {unlimited ? "∞" : total}
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

  function load() {
    setError("");
    api
      .get("/organizations/me")
      .then(setOrg)
      .catch(() => {
        setTimeout(() => {
          api
            .get("/organizations/me")
            .then(setOrg)
            .catch((e2) => setError(e2.message));
        }, 1000);
      });
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(load, []);

  return (
    <>
      <Header title="Settings" />
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
                  {org.id}
                </span>
                <span className="text-gray-500">Tier</span>
                <span>
                  {(() => {
                    const t = TIER_LABELS[org.tier] ?? TIER_LABELS.free;
                    return (
                      <span
                        className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${t.color}`}
                      >
                        {t.label} — {t.price}
                      </span>
                    );
                  })()}
                </span>
              </div>
              {org.tier !== "pro" && org.tier !== "enterprise" && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <a
                    href="/billing"
                    className="inline-block px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
                  >
                    {org.tier === "free" ? "Upgrade to Starter — $5/mo" : "Upgrade to Pro — $25/mo"}
                  </a>
                </div>
              )}
            </div>

            {org.quotas && org.usage && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-sm font-semibold text-gray-900 mb-4">
                  Usage &amp; Quotas
                </h2>
                <div className="space-y-4">
                  <QuotaBar
                    label="Inboxes"
                    used={org.usage.inboxes ?? 0}
                    total={org.quotas.max_inboxes ?? 0}
                  />
                  <QuotaBar
                    label="Pods"
                    used={org.usage.pods ?? 0}
                    total={org.quotas.max_pods ?? 0}
                  />
                  <QuotaBar
                    label="API Keys"
                    used={org.usage.api_keys ?? 0}
                    total={org.quotas.max_api_keys ?? 0}
                  />
                  <QuotaBar
                    label="Custom Domains"
                    used={org.usage.domains ?? 0}
                    total={org.quotas.max_domains ?? 0}
                  />
                  <QuotaBar
                    label="Webhooks"
                    used={org.usage.webhooks ?? 0}
                    total={org.quotas.max_webhooks ?? 0}
                  />
                </div>
                <p className="mt-4 text-xs text-gray-500">
                  Messages/day: <span className="font-medium">{org.quotas.max_messages_per_day ?? 0}</span> · AI calls/mo: <span className="font-medium">{org.quotas.ai_calls_per_month ?? 0}</span> · Retention: <span className="font-medium">{org.quotas.retention_days ?? 0} days</span>
                </p>
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
