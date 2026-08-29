import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import Header from "../components/Header";

interface Agent {
  agent_id: string;
  name: string;
  email?: string;
  status?: string;
}

interface ChannelRecord {
  channel?: string;
  details?: Record<string, string | undefined>;
  config?: Record<string, string | undefined>;
  status?: string;
}

interface ChannelsResponse {
  channels?: ChannelRecord[];
}

interface MessagesResponse {
  messages?: Message[];
  data?: Message[];
}

interface Message {
  message_id: string;
  from?: string | { name?: string; address: string };
  from_addr?: string | { name?: string; address: string };
  subject?: string;
  body_text?: string;
  received_at?: string;
  created_at?: string;
  labels?: string[];
  direction?: string;
}

function emailChannelDetails(channels: ChannelRecord[]): { email?: string; status?: string } {
  const email = channels.find((channel) => channel?.channel === "email");
  const details = email?.details || email?.config || {};
  return {
    email: details.address || details.email,
    status: email?.status,
  };
}

function formatFrom(fromAddr: Message["from"]): string {
  if (typeof fromAddr === "string") return fromAddr;
  if (fromAddr && typeof fromAddr === "object") {
    const name = fromAddr.name;
    const address = fromAddr.address;
    return name ? `${name} <${address}>` : address || "";
  }
  return "";
}

export default function InboxDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");

  async function load() {
    if (!id) return;
    setError("");
    try {
      const [agentResp, channelsResp, messagesResp] = await Promise.all([
        api.get(`/agents/${id}`),
        api.get(`/agents/${id}/channels`),
        api.get(`/agents/${id}/messages?limit=100`),
      ]) as [Agent, ChannelsResponse, MessagesResponse];
      setAgent({
        ...agentResp,
        ...emailChannelDetails(channelsResp?.channels || []),
      });
      setMessages(messagesResp?.messages || messagesResp?.data || []);
    } catch {
      setTimeout(async () => {
        try {
          const messagesResp = await api.get(`/agents/${id}/messages?limit=100`) as MessagesResponse;
          setMessages(messagesResp?.messages || messagesResp?.data || []);
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Failed to load agent");
        }
      }, 1000);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  return (
    <>
      <Header title={agent?.name || "Agent"} />
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

        {agent && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
            <div className="flex flex-wrap items-center gap-6">
              <div>
                <p className="text-sm text-gray-500">Agent</p>
                <p className="font-medium text-gray-900">{agent.name}</p>
                <p className="font-mono text-xs text-gray-400">{agent.agent_id}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Email Channel</p>
                <p className="font-mono text-sm text-gray-900">{agent.email || "--"}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Status</p>
                <span
                  className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${
                    agent.status === "active"
                      ? "bg-green-100 text-green-700"
                      : "bg-gray-100 text-gray-700"
                  }`}
                >
                  {agent.status || "unknown"}
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
            {messages.map((msg) => {
              const isUnread = !(msg.labels || []).includes("read");
              const timestamp = msg.received_at || msg.created_at || "";
              return (
                <Link
                  key={msg.message_id}
                  to={`/agents/${id}/messages/${msg.message_id}`}
                  className={`block px-6 py-4 hover:bg-gray-50 ${isUnread ? "bg-indigo-50/30" : ""}`}
                >
                  <div className="flex justify-between items-start">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        {isUnread && (
                          <span className="w-2 h-2 rounded-full bg-indigo-600 shrink-0" />
                        )}
                        <p
                          className={`text-sm truncate ${isUnread ? "font-semibold text-gray-900" : "text-gray-700"}`}
                        >
                          {formatFrom(msg.from || msg.from_addr)}
                        </p>
                      </div>
                      <p className="text-sm text-gray-900 mt-0.5 truncate">
                        {msg.subject || "(no subject)"}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5 truncate">
                        {msg.body_text || ""}
                      </p>
                    </div>
                    <p className="text-xs text-gray-400 ml-4 shrink-0">
                      {timestamp ? new Date(timestamp).toLocaleString() : "--"}
                    </p>
                  </div>
                </Link>
              );
            })}
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
