import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import Header from "../components/Header";

interface OrgInfo {
  id: string;
  name: string;
  email: string;
  tier: string;
  status: string;
  settings?: Record<string, any>;
  quotas?: { inboxes: number; messages_per_day: number };
  usage?: { inboxes: number; pods: number };
}

export default function DashboardPage() {
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

  useEffect(load, []);

  return (
    <>
      <Header title="Dashboard" />
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
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <p className="text-sm text-gray-500">Organization</p>
                <p className="text-2xl font-semibold text-gray-900 mt-1">
                  {org.name}
                </p>
                <span className="inline-block mt-2 px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-100 text-indigo-700">
                  {org.tier || "free"}
                </span>
              </div>
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <p className="text-sm text-gray-500">Inboxes</p>
                <p className="text-2xl font-semibold text-gray-900 mt-1">
                  {org.usage?.inboxes ?? "--"}
                </p>
                {org.quotas && (
                  <p className="text-xs text-gray-400 mt-2">
                    of {org.quotas.inboxes} allowed
                  </p>
                )}
              </div>
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <p className="text-sm text-gray-500">Pods</p>
                <p className="text-2xl font-semibold text-gray-900 mt-1">
                  {org.usage?.pods ?? "--"}
                </p>
                {org.quotas && (
                  <p className="text-xs text-gray-400 mt-2">
                    of {org.quotas.messages_per_day}/day
                  </p>
                )}
              </div>
            </div>

            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Quick Actions
              </h2>
              <div className="flex flex-wrap gap-3">
                <Link
                  to="/inboxes"
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
                >
                  Manage Inboxes
                </Link>
                <Link
                  to="/api-keys"
                  className="px-4 py-2 bg-white text-gray-700 text-sm font-medium rounded-md border border-gray-300 hover:bg-gray-50"
                >
                  View API Keys
                </Link>
                <Link
                  to="/domains"
                  className="px-4 py-2 bg-white text-gray-700 text-sm font-medium rounded-md border border-gray-300 hover:bg-gray-50"
                >
                  Configure Domains
                </Link>
              </div>
            </div>
          </>
        )}

        {!org && !error && (
          <div className="text-gray-400 text-sm">Loading...</div>
        )}
      </div>
    </>
  );
}
