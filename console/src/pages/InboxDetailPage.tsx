import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import Header from "../components/Header";

interface Inbox {
  id: string;
  email: string;
  display_name: string;
  status: string;
}

interface Message {
  id: string;
  from_addr: string | { name?: string; address: string };
  subject: string;
  snippet: string;
  created_at: string;
  is_read: boolean;
  direction?: string;
}

function formatFrom(from_addr: Message["from_addr"]): string {
  if (typeof from_addr === "string") return from_addr;
  if (from_addr && typeof from_addr === "object") {
    const name = from_addr.name;
    const address = from_addr.address;
    return name ? `${name} <${address}>` : address || "";
  }
  return "";
}

export default function InboxDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");

  function load() {
    if (!id) return;
    setError("");
    api
      .get(`/inboxes/${id}`)
      .then(setInbox)
      .catch(() => {
        setTimeout(() => {
          api.get(`/inboxes/${id}`).then(setInbox).catch(() => {});
        }, 1000);
      });
    api
      .get(`/inboxes/${id}/messages`)
      .then((resp: any) => setMessages(resp?.data || []))
      .catch(() => {
        setTimeout(() => {
          api
            .get(`/inboxes/${id}/messages`)
            .then((resp: any) => setMessages(resp?.data || []))
            .catch((e2) => setError(e2.message));
        }, 1000);
      });
  }

  useEffect(load, [id]);

  return (
    <>
      <Header title={inbox?.email || "Inbox"} />
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

        {inbox && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
            <div className="flex items-center gap-4">
              <div>
                <p className="text-sm text-gray-500">Email</p>
                <p className="font-medium text-gray-900">{inbox.email}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Display Name</p>
                <p className="font-medium text-gray-900">
                  {inbox.display_name || "--"}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Status</p>
                <span
                  className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${
                    inbox.status === "active"
                      ? "bg-green-100 text-green-700"
                      : "bg-gray-100 text-gray-700"
                  }`}
                >
                  {inbox.status}
                </span>
              </div>
            </div>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-sm font-semibold text-gray-900">Messages</h2>
          </div>
          <div className="divide-y divide-gray-200">
            {messages.map((msg) => (
              <Link
                key={msg.id}
                to={`/inboxes/${id}/messages/${msg.id}`}
                className={`block px-6 py-4 hover:bg-gray-50 ${!msg.is_read ? "bg-indigo-50/30" : ""}`}
              >
                <div className="flex justify-between items-start">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {!msg.is_read && (
                        <span className="w-2 h-2 rounded-full bg-indigo-600 shrink-0" />
                      )}
                      <p
                        className={`text-sm truncate ${!msg.is_read ? "font-semibold text-gray-900" : "text-gray-700"}`}
                      >
                        {formatFrom(msg.from_addr)}
                      </p>
                    </div>
                    <p className="text-sm text-gray-900 mt-0.5 truncate">
                      {msg.subject || "(no subject)"}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5 truncate">
                      {msg.snippet}
                    </p>
                  </div>
                  <p className="text-xs text-gray-400 ml-4 shrink-0">
                    {new Date(msg.created_at).toLocaleString()}
                  </p>
                </div>
              </Link>
            ))}
            {messages.length === 0 && (
              <div className="px-6 py-12 text-center text-sm text-gray-400">
                No messages yet.
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
