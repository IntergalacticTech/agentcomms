import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import Header from "../components/Header";

interface FullMessage {
  message_id: string;
  inbox_id: string;
  from: string;
  to: string;
  subject: string;
  body_text: string;
  body_html: string;
  received_at: string;
  headers: Record<string, string>;
}

export default function MessagePage() {
  const { id, mid } = useParams<{ id: string; mid: string }>();
  const [message, setMessage] = useState<FullMessage | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id || !mid) return;
    api
      .get(`/inboxes/${id}/messages/${mid}`)
      .then(setMessage)
      .catch((e) => setError(e.message));
  }, [id, mid]);

  return (
    <>
      <Header title="Message" />
      <div className="p-8">
        <Link
          to={`/inboxes/${id}`}
          className="text-sm text-indigo-600 hover:text-indigo-700 mb-4 inline-block"
        >
          &larr; Back to inbox
        </Link>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm">
            {error}
          </div>
        )}

        {message && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 space-y-2">
              <h2 className="text-lg font-semibold text-gray-900">
                {message.subject || "(no subject)"}
              </h2>
              <div className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 text-sm">
                <span className="text-gray-500">From</span>
                <span className="text-gray-900">{message.from}</span>
                <span className="text-gray-500">To</span>
                <span className="text-gray-900">{message.to}</span>
                <span className="text-gray-500">Date</span>
                <span className="text-gray-900">
                  {new Date(message.received_at).toLocaleString()}
                </span>
              </div>
            </div>
            <div className="px-6 py-6">
              {message.body_html ? (
                <div
                  className="prose prose-sm max-w-none"
                  dangerouslySetInnerHTML={{ __html: message.body_html }}
                />
              ) : (
                <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans">
                  {message.body_text}
                </pre>
              )}
            </div>
          </div>
        )}

        {!message && !error && (
          <div className="text-gray-400 text-sm">Loading...</div>
        )}
      </div>
    </>
  );
}
