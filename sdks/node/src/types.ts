export interface PaginatedResponse<T> {
  data: T[];
  next_page_token?: string;
  has_more: boolean;
}

export interface Organization {
  id: string;
  name: string;
  plan: string;
  created_at: string;
  updated_at: string;
}

export interface Recipient {
  name?: string;
  address: string;
}

export interface Inbox {
  id: string;
  email: string;
  display_name?: string;
  pod_id?: string;
  organization_id: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  inbox_id: string;
  thread_id?: string;
  from: Recipient;
  to: Recipient[];
  cc?: Recipient[];
  bcc?: Recipient[];
  subject: string;
  body_text?: string;
  body_html?: string;
  is_read: boolean;
  is_starred: boolean;
  labels?: string[];
  direction: "inbound" | "outbound";
  created_at: string;
  updated_at: string;
}

export interface Thread {
  id: string;
  inbox_id: string;
  subject: string;
  message_count: number;
  last_message_at: string;
  created_at: string;
  updated_at: string;
}

export interface Draft {
  id: string;
  inbox_id: string;
  to?: Recipient[];
  cc?: Recipient[];
  bcc?: Recipient[];
  subject?: string;
  body_text?: string;
  body_html?: string;
  created_at: string;
  updated_at: string;
}

export interface Pod {
  id: string;
  name: string;
  description?: string;
  organization_id: string;
  inbox_count?: number;
  created_at: string;
  updated_at: string;
}

export interface Domain {
  id: string;
  domain: string;
  status: string;
  verified: boolean;
  dns_records?: DnsRecord[];
  organization_id: string;
  created_at: string;
  updated_at: string;
}

export interface DnsRecord {
  type: string;
  name: string;
  value: string;
  priority?: number;
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  secret?: string;
  organization_id: string;
  created_at: string;
  updated_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  key?: string;
  last_used_at?: string;
  created_at: string;
  updated_at: string;
}

// Option types

export interface CreateInboxOptions {
  display_name?: string;
  email?: string;
  pod_id?: string;
}

export interface ListInboxesOptions {
  pod_id?: string;
  limit?: number;
  page_token?: string;
}

export interface SendMessageOptions {
  to: Recipient[];
  subject: string;
  body_text?: string;
  body_html?: string;
}

export interface ReplyMessageOptions {
  body_text?: string;
  body_html?: string;
}

export interface ForwardMessageOptions {
  to: Recipient[];
  body_text?: string;
}

export interface UpdateMessageOptions {
  is_read?: boolean;
  is_starred?: boolean;
  labels?: string[];
}

export interface ListMessagesOptions {
  limit?: number;
  page_token?: string;
}

export interface WaitForMessageOptions {
  timeout?: number;
  sender?: string;
  subject_contains?: string;
}

export interface ExtractOtpOptions {
  timeout?: number;
  sender?: string;
  subject_contains?: string;
}

export interface ExtractOtpResult {
  code: string | null;
  message_id: string;
  from: string;
  subject: string;
}

export interface CreatePodOptions {
  name: string;
  description?: string;
}

export interface ListPodOptions {
  limit?: number;
  page_token?: string;
}

export interface CreateDomainOptions {
  domain: string;
}

export interface ListDomainOptions {
  limit?: number;
  page_token?: string;
}

export interface CreateWebhookOptions {
  url: string;
  events: string[];
  active?: boolean;
}

export interface UpdateWebhookOptions {
  url?: string;
  events?: string[];
  active?: boolean;
}

export interface ListWebhookOptions {
  limit?: number;
  page_token?: string;
}

export interface CreateApiKeyOptions {
  name: string;
}

export interface ListApiKeyOptions {
  limit?: number;
  page_token?: string;
}
