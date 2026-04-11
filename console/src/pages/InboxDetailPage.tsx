import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import Header from "../components/Header";

interface Inbox {
  inbox_id: string;
  email: string;
  display_name: string;
  status: string;
}

interface Message {
  message_id: string;
  from: string;
  subject: string;
  snippet: string;
  received_at: string;
  is_read: boolean;
}

export default function InboxDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    api
      .get(`/inboxes/${id}`)
      .then(setInbox)
      .catch((e) => setError(e.message));
    api
      .get(`/inboxes/${id}/messages`)
      .then((data) => setMessages(data.messages || data || []))
      .catch((e) => setError(e.message));
  }, [id]);

  return (
    <>
      <Header title={inbox?.email || "Inbox"} />
      <div className="p-8">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm">
            {error}
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
                key={msg.message_id}
                to={`/inboxes/${id}/messages/${msg.message_id}`}
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
                        {msg.from}
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
                    {new Date(msg.received_at).toLocaleString()}
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
