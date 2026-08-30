# AgentComms pivot announcement (customer email template)

> **When to send:** ~10 days before cutover date.
> **Audience:** Every paying customer (pull from CRM, not just active API key holders).
> **From:** founders@ or support@ — personal tone preferred.
> **Template variables:** Replace all `<PLACEHOLDERS>` before sending.

---

**Subject:** Your FreeMail account is moving to AgentComms on `<CUTOVER_DATE>`

---

Hi `<FIRST_NAME>`,

When you signed up for FreeMail, we were building "email for AI agents." Over
the past several weeks we've expanded the product to cover the whole
communications surface your agents need — SMS, Slack, Telegram, push
notifications, and more — and renamed it **AgentComms** to reflect that broader
vision.

Your FreeMail account moves to AgentComms on **`<CUTOVER_DATE>`**.

---

### What changes for you

**New API endpoint.**
`api.victorymail.dev` → `api.agentcomms.dev`

Your current SDK will keep working for **90 days** via an automatic redirect:
`api.victorymail.dev` returns HTTP 301s that your HTTP client follows
automatically. After 90 days the old URL returns 410 Gone.

**New SDK packages.**
- Python: `pip install agentcomms` (replaces `freemail`)
- Node: `npm i @agentcomms/client` (replaces `@freemail/client`)

The old packages remain installable for 90 days. They import a deprecation shim
that re-exports from the new packages, so nothing breaks automatically.

**New data model — Inboxes are now called Agents.**
Your existing inbox `inb_abc...` becomes agent `agt_abc...` and acquires a
default email channel `chan_em_abc...`. Messages, threads, webhooks, domains,
and API keys move with it automatically — **no data is lost**.

**Your plan.**
`<CURRENT_PLAN_SPECIFIC_GRANDFATHER_NOTE>`

*(Personalise per customer tier, e.g.: "You're on Pro at $25/mo; starting
`<CUTOVER_DATE>` you move to the new Developer tier at $19/mo for 6 months,
then standard Developer pricing.")*

---

### What stays the same

- Your **API keys** are unchanged and remain valid without any action from you.
- Your **webhook URLs**, **custom domains**, and **DKIM records** continue to work.
- **All your data** (messages, threads, domains, send history) migrates automatically.
- Our **support commitments** to you are unchanged.
- Your application code keeps working at the old URL for **90 days**.

---

### What you need to do

**Nothing is required** — your application will keep working automatically.

But to get the best developer experience, we recommend doing the following
**within 90 days**:

1. **Update your SDK:**
   ```bash
   pip install -U agentcomms          # Python
   npm i @agentcomms/client@latest    # Node
   ```

2. **Change your base URL** from `api.victorymail.dev` to `api.agentcomms.dev`
   (one environment variable in most setups).

3. **Review the migration guide** at
   [docs.agentcomms.dev/migration](https://docs.agentcomms.dev/migration) —
   or see `MIGRATION.md` in your SDK repo — for the field-by-field diff. Most
   handler shapes are identical; a few fields are renamed.

4. **Rename `inb_` prefixes to `agt_`** in any code that constructs IDs
   manually (IDs received from the API continue to work via the redirect for 90
   days, but explicit prefix construction needs updating).

---

### New capabilities you get on day one

On `<CUTOVER_DATE>`, your account immediately gains access to:

- **SMS channels** — attach a phone number to any agent; agents receive and
  send SMS the same way they handle email.
- **Slack + Telegram channels** — agents participate in Slack channels or
  Telegram bots natively.
- **Push notifications** — send push to iOS/Android via your agent.
- **Unified message inbox** — all channels feed a single `/messages` endpoint
  with a consistent payload shape.
- **Agent personas** — define display name, avatar, and tone per agent.

These are all available at `api.agentcomms.dev` immediately; no additional
configuration required to keep using email as before.

---

### Questions?

Reply to this email, or book a 30-minute migration call with me:
[`<CALENDLY_LINK>`](`<CALENDLY_LINK>`)

I'm also in `<SLACK_COMMUNITY_LINK>` if you prefer async.

Thanks for building on FreeMail / AgentComms,

`<YOUR_NAME>`
`<YOUR_TITLE>`
Victory / AgentComms

---

*You're receiving this because you have a paid FreeMail account. To opt out
of product announcements, [click here](`<UNSUBSCRIBE_LINK>`).*
