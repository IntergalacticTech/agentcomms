# SMS Production Setup (Ops Runbook)

This doc walks an operator through everything required to take AgentComms SMS from "code shipped" (current state) to "customers can buy a phone number and start sending."

The Lambdas are already deployed:

- `SmsFn` — handles SMS channel provisioning through `POST /agents/{agent_id}/channels`, currently dependent on provider setup before end-to-end SMS works
- `SmsProcessorFn` — handles inbound SMS via SNS, currently has no SNS subscription so it's idle
- IAM permissions for `sms-voice:SendTextMessage` are in place

What's missing is **AWS account state and 10DLC registration** — this is process work, not code.

---

## TL;DR — The Six Steps

1. **Exit the SMS sandbox** (AWS Support case, 1 business day)
2. **Choose: shared brand or per-customer brands** — recommend **shared brand**
3. **Register a 10DLC brand** with The Campaign Registry via AWS End User Messaging console
4. **Register a 10DLC campaign** under the brand
5. **Buy initial phone numbers** and link them to the campaign
6. **Wire the inbound SNS topic** to `SmsProcessorFn`

After all six, AgentComms can sell SMS as a paid feature.

---

## 1. Exit the SMS sandbox

**Why:** New AWS accounts start with a $1/month sandbox cap on SMS spending, and can only send to verified phone numbers.

**How:**
- Open AWS Support Center → Create case → Service limit increase → Service: "End User Messaging SMS"
- Request type: **Move out of SMS sandbox**
- Justify the request: "AgentComms is an API platform for AI agents. We need to send transactional A2P SMS for OTP delivery and notifications. Volume estimates: ~1,000 messages/day initially, ramping to ~50,000/day at scale. All sends are agent-initiated and we will register every campaign with TCR."
- AWS typically approves within 24 hours.

**Verify:** Once approved, AWS Support ticket closes and `aws sms-voice describe-account-attributes` shows `AccountTier: STANDARD` (no longer `SANDBOX`).

---

## 2. Decide: Shared Brand or Per-Customer Brands

This is the **biggest architectural decision** for SMS at AgentComms. You have two options:

### Option A: Shared Brand (recommended)

We register **one** 10DLC brand with The Campaign Registry under "AgentComms / IntergalacticTech." Every customer's phone number falls under our single brand and one or more umbrella campaigns. Customers don't need to do any registration — they just buy a phone number from us.

**Pros:**
- Customer onboarding is one API call: `POST /agents/{agent_id}/channels` with `{"channel":"sms"}`
- Lower total cost (one brand fee vs. one per customer)
- No customer-side TCR vetting delays
- Faster time to revenue

**Cons:**
- We carry TCPA liability for every message any customer sends
- AWS gives us less throughput headroom because all customer traffic is one campaign
- One bad customer can damage the brand's reputation score and slow down everyone

**Mitigations:**
- Aggressive content filtering (forbidden keywords list, spam classifier on outbound)
- Per-customer rate limits at the AgentComms layer (already shipped via `shared/abuse.py`)
- Auto-suspend on bounce/complaint signals (already shipped via the bounce processor)
- Require customers to attest to opt-in compliance in our ToS

### Option B: Per-Customer Brands (CSP model)

We register as a **Campaign Service Provider** (CSP) with TCR. Each customer registers their own brand + campaign through our flow; we proxy the registration calls to TCR via AWS End User Messaging APIs.

**Pros:**
- TCPA liability flows to the customer (they own the brand)
- Higher per-customer throughput because each campaign has its own limits
- One bad customer doesn't poison the well for others

**Cons:**
- Customer onboarding is multi-step (~2-5 days for TCR vetting per customer)
- Each customer pays brand fee (~$4.50) + campaign vetting (~$41.50) + monthly campaign ($2-10/mo)
- Significant additional UI + API surface to build (registration flow, vetting status polling, error handling)
- We need to be approved as a CSP by TCR — separate process

### Recommendation

**Start with Option A (shared brand).** It's faster to ship, simpler to operate, and lets us validate that customers actually want SMS before investing in per-customer onboarding flows. Migrate high-volume customers to their own brands later if they outgrow the shared campaign or want to own their TCPA posture.

---

## 3. Register a 10DLC Brand

Open the AWS End User Messaging console → SMS → Phone numbers → Origination identities → Register a brand.

**Brand details to provide:**
- Brand name: `AgentComms`
- Legal entity: `IntergalacticTech, LLC` (or whatever the legal name is)
- Tax ID (EIN): _your EIN_
- Address: company HQ
- Vertical: `Technology`
- Brand type: **Standard** (not "low-volume") — Standard gives ~3000 msg/sec, Low-Volume gives ~1
- Brand vetting: skip the optional Aegis vetting unless you want premium throughput later (it's $40 one-time and shaves rate-limit ceilings)

**Cost:** ~$4.50 one-time brand registration fee.
**Time:** Brand registration with TCR is usually instant, but TCR can flag suspicious entries for manual review (1-3 days).

**Verify:** `aws sms-voice describe-registrations` returns the new brand with `RegistrationStatus: COMPLETE`.

---

## 4. Register a 10DLC Campaign

Same console: Phone numbers → Origination identities → Register a campaign under the brand you just created.

**Campaign details:**
- Campaign name: `AgentComms Agent SMS`
- Use case: `2FA / OTP` (most permissive vetting outcome)
- Description: "Transactional SMS for AI agents — delivers OTP codes and notifications to end users who have signed up for AgentComms customer applications. Each end user has explicitly opted in via the customer's signup flow."
- Sample message 1: "Your verification code is 482917. It expires in 10 minutes."
- Sample message 2: "AgentComms: a new device signed in to your account. If this wasn't you, reply STOP."
- Opt-in workflow: link to a public page describing how end users opt in
- Embedded link: NO (links increase carrier filtering)
- Embedded phone: NO
- Age-gated content: NO
- Affiliate marketing: NO
- Direct lending: NO

**Cost:**
- Standard campaign: **$10/month**
- Low-volume campaign: **$2/month** (max ~6,000 messages/day across all numbers on the campaign — fine for a launch)
- One-time campaign vetting: **~$41.50**
- T-Mobile activation fee: $50 (currently waived as of 2026-04)

**Time:** TCR vetting is 1-5 days. T-Mobile sometimes adds a second review.

**Verify:** Campaign status shows `REGISTERED` and `OPERATOR_APPROVAL` for AT&T, T-Mobile, Verizon.

---

## 5. Buy Phone Numbers

Once the campaign is approved, request 10DLC long codes from AWS End User Messaging console → Phone numbers → Request phone number.

**For the launch pool:**
- **Type:** 10DLC
- **Country:** US
- **Number type:** Local
- **Capabilities:** SMS + Voice (Voice is free if you don't use it; useful if you ever ship voice OTP)
- **Two-way:** Yes (required for inbound — see step 6)
- **Quantity:** Start with 5-10 numbers. Each is $1/month. Buy more as customers onboard.

**Cost:** $1/month per number.

**After purchase:** Each number must be linked to the campaign you registered in step 4. Console: select the number → Configurations → Associated campaign → pick the AgentComms campaign.

**Verify:** `aws sms-voice describe-phone-numbers` returns the numbers with `Status: ACTIVE` and the campaign ID populated.

---

## 6. Wire the Inbound SNS Topic to SmsProcessorFn

This is the only **code change** in this runbook (a small CDK update — the Lambda itself is already deployed).

### What needs to happen

End User Messaging delivers inbound SMS to an SNS topic that you configure on each phone number. We need to:

1. Create a single SNS topic `agentcomms-sms-inbound`
2. Configure each AgentComms-owned phone number to publish inbound messages to that topic
3. Subscribe `SmsProcessorFn` to the topic

### CDK changes

In `cdk/lib/stacks/email-stack.ts` (or a new `sms-stack.ts`):

```typescript
this.smsInboundTopic = new sns.Topic(this, "SmsInboundTopic", {
  topicName: `agentcomms-sms-inbound-${props.stage}`,
});
```

In `cdk/lib/stacks/api-stack.ts`, near the existing `smsProcessorFn` definition, subscribe it to that topic and grant SNS invoke permission. The SNS topic ARN gets passed in via `props.smsInboundTopic`:

```typescript
smsProcessorFn.addEventSource(
  new lambda_events.SnsEventSource(props.smsInboundTopic)
);
```

In `cdk/bin/app.ts`, pipe the topic from EmailStack into ApiStack like the existing bounce/complaint topics.

### Console-side wiring (one-time per phone number)

End User Messaging console → Phone numbers → select number → Two-way → Enable → SNS topic ARN: `arn:aws:sns:us-east-1:<AWS_ACCOUNT_ID>:agentcomms-sms-inbound-prod`.

### Customer-side wiring (per agent)

When a customer adds a phone number channel to an agent, we need to:
1. Allocate a number from our pool (or pull a free one from `aws sms-voice describe-phone-numbers`)
2. Store the number on the channel record under `config.phone_number`
3. Add an address index entry for inbound routing: `ADDR#sms#+1XXXXXXXXXX`
4. Charge the customer $1/month for the number lease

This is handled through `POST /agents/{agent_id}/channels` once provider setup is complete.

---

## Cost Summary

| Line item | Cost | When |
|---|---|---|
| Sandbox exit | $0 | 1-time, free |
| Brand registration (TCR) | ~$4.50 | 1-time |
| Campaign vetting (TCR) | ~$41.50 | 1-time |
| T-Mobile activation | $0 (waived 2026) | 1-time |
| Standard campaign | $10/mo | Recurring |
| 10DLC long code lease | $1/mo per number | Recurring |
| Outbound US SMS | ~$0.00645 base + ~$0.00302 carrier (10DLC) | Per message |
| Inbound US SMS | ~$0.0075 | Per message |

**Launch baseline: ~$15/month fixed (1 campaign + 5 numbers) plus per-message charges.**

**Per customer with 1 inbox, 50 messages/month:**
- Number lease: $1/mo
- 50 outbound: $0.475
- Total: **~$1.48/mo cost** → break-even at $5/mo Starter tier with the SMS add-on

---

## What AgentComms Charges Customers for SMS

Recommended pricing (subject to your input):

- **SMS phone number lease**: $2/month per number, included in Pro tier ($25/mo) or +$2/mo on Starter
- **Outbound SMS overage**: $0.02/msg above 100/month included on Starter, above 1000/month included on Pro (~3× our cost — same markup as email)
- **Inbound SMS / OTP capture**: included free with the number lease (we eat the $0.0075/msg cost)

---

## Decisions Still Needed

1. **Shared brand vs. CSP** — see step 2. My recommendation: shared.
2. **Standard vs. low-volume campaign** — Standard ($10/mo) gets us higher throughput; low-volume ($2/mo) caps us at ~6k msg/day. Recommend Standard since the marginal $8/mo is trivial vs. operational hassle of hitting the cap.
3. **Whether to also register a toll-free number** — toll-free has different (less stringent) registration but is US-only and ~$2/month more per number. Useful for customers who want a 1-800-style brand. Defer until a customer asks.
4. **Voice OTP** — same v2 API, ~3-5 days to wire up. Could ship alongside SMS or as a Phase 2 add-on.
5. **International SMS** — only US is covered by 10DLC. International requires per-country sender IDs and is genuinely complex. Defer to Enterprise tier.

---

## How to Pull the Trigger

When you're ready, the order is:

1. **Today:** Open the SMS sandbox-exit support case (Step 1). Free, fast.
2. **Tomorrow:** Once sandbox is exited, register the brand (Step 3). Wait for TCR.
3. **Day 3-5:** Brand approved → register the campaign (Step 4). Wait for TCR.
4. **Day 6-10:** Campaign approved → buy 5 phone numbers (Step 5).
5. **Day 10:** Wire the SNS topic into CDK (Step 6) and deploy `VictoryMail-Api-dev`.
6. **Day 11:** Manual smoke test — send an SMS from one of the phone numbers using `aws sms-voice send-text-message`, then send one to it from your personal phone and verify `SmsProcessorFn` writes it to DynamoDB.
7. **Day 12+:** Harden SMS channel provisioning and ship SMS as a production hosted feature.

Total wall-clock from "ready to start" to "first customer can buy SMS": **~2 weeks**, almost all waiting on TCR. Active engineering time is ~1 day.

---

## Reference: AWS Documentation

- [End User Messaging SMS sandbox](https://docs.aws.amazon.com/sms-voice/latest/userguide/sandbox.html)
- [10DLC brand registration](https://docs.aws.amazon.com/sms-voice/latest/userguide/registrations-brand.html)
- [10DLC campaign registration](https://docs.aws.amazon.com/sms-voice/latest/userguide/registrations-campaign.html)
- [Two-way SMS configuration](https://docs.aws.amazon.com/sms-voice/latest/userguide/phone-numbers-two-way-sms.html)
- [Pricing](https://aws.amazon.com/end-user-messaging/pricing/)
- [TCR documentation](https://www.campaignregistry.com)
