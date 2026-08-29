import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import DOMPurify, { type Config } from "dompurify";
import { api } from "../api/client";
import Header from "../components/Header";

const SANITIZE_CONFIG: Config = {
  FORBID_TAGS: [
    "script",
    "style",
    "iframe",
    "frame",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "textarea",
    "select",
    "option",
    "link",
    "meta",
    "base",
    "svg",
    "math",
  ],
  FORBID_ATTR: ["style"],
  ALLOW_DATA_ATTR: false,
  ALLOWED_URI_REGEXP: /^(?:https?|mailto|tel):/i,
};

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer nofollow");
  }
});

interface Party {
  name?: string;
  display_name?: string;
  address: string;
}

interface FullMessage {
  message_id: string;
  agent_id: string;
  from?: string | Party;
  from_addr?: string | Party;
  to?: Array<string | Party> | string;
  subject?: string;
  body_text?: string;
  body_html?: string;
  received_at?: string;
  created_at?: string;
  labels?: string[];
  channel_native?: Record<string, unknown>;
}

function formatAddr(addr?: string | Party): string {
  if (!addr) return "";
  if (typeof addr === "string") return addr;
  const name = addr.display_name || addr.name;
  return name ? `${name} <${addr.address}>` : addr.address || "";
}

function formatRecipients(to?: FullMessage["to"]): string {
  if (!to) return "";
  if (typeof to === "string") return to;
  return to.map(formatAddr).filter(Boolean).join(", ");
}

export default function MessagePage() {
  const { id, mid } = useParams<{ id: string; mid: string }>();
  const [message, setMessage] = useState<FullMessage | null>(null);
  const [error, setError] = useState("");

  async function load() {
    if (!id || !mid) return;
    setError("");
    try {
      setMessage(await api.get(`/agents/${id}/messages/${mid}`));
    } catch {
      setTimeout(async () => {
        try {
          setMessage(await api.get(`/agents/${id}/messages/${mid}`));
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Failed to load message");
        }
      }, 1000);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, mid]);

  const safeHtml = message?.body_html
    ? DOMPurify.sanitize(message.body_html, SANITIZE_CONFIG)
    : "";
  const timestamp = message?.received_at || message?.created_at || "";

  return (
    <>
      <Header title="Message" />
      <div className="p-8">
        <Link
          to={`/agents/${id}`}
          className="text-sm text-indigo-600 hover:text-indigo-700 mb-4 inline-block"
        >
          &larr; Back to agent
        </Link>

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

        {message && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 space-y-2">
              <h2 className="text-lg font-semibold text-gray-900">
                {message.subject || "(no subject)"}
              </h2>
              <div className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 text-sm">
                <span className="text-gray-500">From</span>
                <span className="text-gray-900">{formatAddr(message.from || message.from_addr)}</span>
                <span className="text-gray-500">To</span>
                <span className="text-gray-900">{formatRecipients(message.to)}</span>
                <span className="text-gray-500">Date</span>
                <span className="text-gray-900">
                  {timestamp ? new Date(timestamp).toLocaleString() : "--"}
                </span>
              </div>
            </div>
            <div className="px-6 py-6">
              {safeHtml ? (
                <div
                  className="prose prose-sm max-w-none"
                  dangerouslySetInnerHTML={{ __html: safeHtml }}
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
