# Custom Domains

AgentComms uses Amazon SES for email send and receive in the default AWS deployment. Custom domains are registered at the org level, then email channels can provision addresses on verified domains.

## Register a Domain

```bash
curl -sS -X POST https://api.agentcomms.dev/v1/domains \
  -H "Authorization: Bearer ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"domain_name": "mail.example.com"}'
```

Response:

```json
{
  "domain_id": "dom_...",
  "domain_name": "mail.example.com",
  "status": "pending_dns",
  "dkim_tokens": ["token1", "token2", "token3"],
  "dns_records": {
    "mx": {
      "type": "MX",
      "name": "mail.example.com",
      "value": "10 inbound-smtp.us-east-1.amazonaws.com",
      "ttl": 1800
    },
    "spf": {
      "type": "TXT",
      "name": "mail.example.com",
      "value": "v=spf1 include:amazonses.com ~all",
      "ttl": 3600
    },
    "dkim": [
      {
        "type": "CNAME",
        "name": "token1._domainkey.mail.example.com",
        "value": "token1.dkim.amazonses.com",
        "ttl": 1800
      }
    ],
    "dmarc": {
      "type": "TXT",
      "name": "_dmarc.mail.example.com",
      "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc@mail.example.com",
      "ttl": 3600
    }
  }
}
```

DKIM tokens are issued by SES per domain. Use the exact records returned by your API response.

## Publish DNS

At your DNS provider, publish:

| Type | Name | Value |
|---|---|---|
| MX | `mail.example.com` | `10 inbound-smtp.us-east-1.amazonaws.com` |
| TXT | `mail.example.com` | `v=spf1 include:amazonses.com ~all` |
| CNAME | `<token>._domainkey.mail.example.com` | `<token>.dkim.amazonses.com` |
| TXT | `_dmarc.mail.example.com` | `v=DMARC1; p=quarantine; rua=mailto:dmarc@mail.example.com` |

If you already have an SPF record, merge `include:amazonses.com` into the existing record instead of publishing a second SPF record.

## Verify

```bash
curl -sS -X POST https://api.agentcomms.dev/v1/domains/dom_.../verify \
  -H "Authorization: Bearer ak_live_YOUR_KEY"
```

Check status:

```bash
curl -sS https://api.agentcomms.dev/v1/domains/dom_... \
  -H "Authorization: Bearer ak_live_YOUR_KEY"
```

Export a BIND-style zone file:

```bash
curl -sS https://api.agentcomms.dev/v1/domains/dom_.../zone-file \
  -H "Authorization: Bearer ak_live_YOUR_KEY"
```

## Provision an Email Channel

After the domain is verified, create an email channel under an agent:

```bash
curl -sS -X POST https://api.agentcomms.dev/v1/agents/agt_.../channels \
  -H "Authorization: Bearer ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "email",
    "mode": "provision",
    "config": {
      "local_part": "invoice",
      "domain": "mail.example.com"
    }
  }'
```

## SDKs

Python:

```python
from agentcomms import Client

client = Client(api_key="ak_live_YOUR_KEY")
domain = client.domains.create(domain_name="mail.example.com")
client.domains.verify(domain.domain_id)
```

Node:

```typescript
import { Client } from "@agentcomms/client";

const client = new Client({ apiKey: "ak_live_YOUR_KEY" });
const domain = await client.domains.create({ domain_name: "mail.example.com" });
await client.domains.verify(domain.domain_id);
```

## Troubleshooting

- DNS propagation can take minutes to hours. Use `dig MX`, `dig TXT`, and `dig CNAME` to verify records are externally visible.
- Some DNS providers append the zone name automatically. Avoid names like `token._domainkey.mail.example.com.example.com`.
- SES inbound email is regional. The default docs assume `us-east-1`; adjust records if your deployment uses another supported SES inbound region.
