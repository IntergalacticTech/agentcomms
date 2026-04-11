# Deliverability Architecture

## Overview

Deliverability is the single most critical operational concern for a multi-tenant email platform. One tenant with poor sending practices can poison the IP reputation for all tenants. AgentMail's deliverability architecture uses layered IP isolation, real-time per-tenant reputation monitoring, automatic throttling and suspension, suppression list management, and SES Virtual Deliverability Manager to maintain inbox placement rates above 95%.

---

## Table of Contents

- [IP Pool Strategy](#ip-pool-strategy)
- [IP Warming Schedule](#ip-warming-schedule)
- [SES Managed Warming with VDM](#ses-managed-warming-with-vdm)
- [Per-Configuration-Set Sending Quotas](#per-configuration-set-sending-quotas)
- [Virtual Deliverability Manager (VDM)](#virtual-deliverability-manager-vdm)
- [Reputation Monitoring](#reputation-monitoring)
- [Per-Tenant Reputation Isolation](#per-tenant-reputation-isolation)
- [Suppression List Management](#suppression-list-management)
- [Feedback Loops and ISP Relationships](#feedback-loops-and-isp-relationships)
- [CloudWatch Alarms for Deliverability](#cloudwatch-alarms-for-deliverability)

---

## IP Pool Strategy

SES supports multiple IP pools, each containing one or more dedicated IPs. By assigning tenants to different pools based on their tier and sending behavior, we isolate reputation risk.

### Pool Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SES Account                                  │
│                                                                     │
│  ┌───────────────────┐  ┌───────────────────┐                      │
│  │ Pool: ses-default  │  │ Pool: standard     │                     │
│  │ (SES shared IPs)   │  │ (2-4 dedicated)    │                     │
│  │                     │  │                     │                    │
│  │ Used by:            │  │ Used by:            │                   │
│  │ - Free tier tenants │  │ - Standard tenants  │                   │
│  │ - Trial accounts    │  │ - Low-medium volume │                   │
│  │                     │  │                     │                    │
│  │ Cost: $0/mo         │  │ Cost: $24.95/IP/mo  │                   │
│  │                     │  │ Total: ~$50-100/mo  │                    │
│  └───────────────────┘  └───────────────────┘                      │
│                                                                     │
│  ┌───────────────────┐  ┌───────────────────┐                      │
│  │ Pool: premium      │  │ Pool: transactional│                     │
│  │ (per-tenant IPs)   │  │ (dedicated)         │                    │
│  │                     │  │                     │                    │
│  │ Used by:            │  │ Used by:            │                   │
│  │ - Enterprise tenants│  │ - All tenants       │                   │
│  │ - High volume       │  │ - Transactional     │                   │
│  │ - Reputation-       │  │   email only        │                   │
│  │   sensitive          │  │ - Receipts, alerts  │                   │
│  │                     │  │                     │                    │
│  │ Cost: $24.95/IP/mo  │  │ Cost: $24.95/IP/mo │                   │
│  │ per tenant          │  │ Total: ~$50-75/mo  │                    │
│  └───────────────────┘  └───────────────────┘                      │
│                                                                     │
│  ┌───────────────────┐                                              │
│  │ Pool: quarantine   │                                             │
│  │ (1 dedicated IP)   │                                             │
│  │                     │                                            │
│  │ Used by:            │                                            │
│  │ - Tenants under     │                                            │
│  │   reputation review │                                            │
│  │ - New unverified    │                                            │
│  │   high-volume       │                                            │
│  │   senders           │                                            │
│  │                     │                                            │
│  │ Cost: $24.95/mo     │                                            │
│  └───────────────────┘                                              │
└─────────────────────────────────────────────────────────────────────┘
```

### Pool Configuration

```python
import boto3

ses_v2 = boto3.client('sesv2', region_name='us-east-1')

def setup_ip_pools():
    """Create all IP pools for the AgentMail platform."""

    pools = [
        {
            'name': 'agentmail-standard',
            'description': 'Shared dedicated IPs for standard-tier tenants',
            'scaling_mode': 'STANDARD',  # Manual IP management
        },
        {
            'name': 'agentmail-premium',
            'description': 'Per-tenant dedicated IPs for enterprise customers',
            'scaling_mode': 'STANDARD',
        },
        {
            'name': 'agentmail-transactional',
            'description': 'Dedicated IPs for transactional email (receipts, alerts)',
            'scaling_mode': 'STANDARD',
        },
        {
            'name': 'agentmail-quarantine',
            'description': 'Isolation pool for tenants under reputation review',
            'scaling_mode': 'STANDARD',
        },
        {
            'name': 'agentmail-warming',
            'description': 'Pool for IPs currently in the warming phase',
            'scaling_mode': 'MANAGED',  # SES manages warming automatically
        },
    ]

    for pool in pools:
        ses_v2.create_dedicated_ip_pool(
            PoolName=pool['name'],
            ScalingMode=pool['scaling_mode'],
            Tags=[
                {'Key': 'managed_by', 'Value': 'agentmail'},
                {'Key': 'description', 'Value': pool['description']}
            ]
        )


def assign_tenant_to_pool(org_id: str, tier: str):
    """Assign a tenant's configuration set to the appropriate IP pool."""
    config_set_name = f'agentmail-{org_id}'

    pool_map = {
        'free': None,                       # SES shared (no dedicated pool)
        'standard': 'agentmail-standard',
        'premium': 'agentmail-premium',
        'enterprise': 'agentmail-premium',  # Dedicated per-tenant IP created separately
    }

    pool = pool_map.get(tier)

    if pool:
        ses_v2.put_configuration_set_delivery_options(
            ConfigurationSetName=config_set_name,
            TlsPolicy='REQUIRE',
            SendingPoolName=pool
        )
    else:
        # Free tier: use SES shared IPs (default, no pool assignment)
        ses_v2.put_configuration_set_delivery_options(
            ConfigurationSetName=config_set_name,
            TlsPolicy='OPTIONAL'
        )
```

### Per-Tenant Dedicated IPs (Enterprise)

```python
def provision_enterprise_dedicated_ip(org_id: str):
    """
    Provision a dedicated IP for an enterprise tenant.

    The IP starts in the warming pool and is moved to
    the premium pool after warming is complete.
    """
    # Request a new dedicated IP
    # Note: SES allocates IPs from their pool -- you don't choose the IP
    # IPs are $24.95/month each

    # For VDM-managed warming:
    ses_v2.put_dedicated_ip_in_pool(
        Ip='auto',  # Allocated by AWS
        DestinationPoolName='agentmail-warming',
    )

    # Store mapping in DynamoDB
    table = dynamodb.Table(TABLE_NAME)
    table.put_item(Item={
        'PK': f'ORG#{org_id}',
        'SK': 'DEDICATED_IP',
        'ip_address': 'pending',  # Updated when allocated
        'pool': 'agentmail-warming',
        'status': 'warming',
        'created_at': int(time.time() * 1000)
    })
```

---

## IP Warming Schedule

New dedicated IPs have no sending history and no reputation with ISPs. Sending high volume from a cold IP results in blocks and bounces. The warming process gradually increases daily volume over 45 days.

### Manual Warming Schedule

| Day | Daily Volume | Cumulative | Notes |
|---|---|---|---|
| 1 | 200 | 200 | Start very low |
| 2 | 500 | 700 | |
| 3 | 1,000 | 1,700 | |
| 4 | 2,000 | 3,700 | |
| 5 | 5,000 | 8,700 | |
| 6 | 10,000 | 18,700 | |
| 7 | 20,000 | 38,700 | End of week 1 |
| 8-10 | 30,000 | 128,700 | |
| 11-14 | 50,000 | 328,700 | End of week 2 |
| 15-21 | 75,000 | 853,700 | Week 3: moderate volume |
| 22-28 | 100,000 | 1,553,700 | Week 4: building reputation |
| 29-35 | 200,000 | 2,953,700 | Week 5: significant volume |
| 36-42 | 500,000 | 6,453,700 | Week 6: high volume |
| 43-45 | Full volume | - | Warming complete |

### Warming Implementation

```python
"""
Lambda: ip-warming-manager
Triggered by: EventBridge rule (daily at 00:00 UTC)
"""

WARMING_SCHEDULE = [
    # (day_start, day_end, daily_limit)
    (1, 1, 200),
    (2, 2, 500),
    (3, 3, 1000),
    (4, 4, 2000),
    (5, 5, 5000),
    (6, 6, 10000),
    (7, 7, 20000),
    (8, 10, 30000),
    (11, 14, 50000),
    (15, 21, 75000),
    (22, 28, 100000),
    (29, 35, 200000),
    (36, 42, 500000),
    (43, 45, 1000000),  # Effectively unlimited after day 45
]


def get_warming_limit(day: int) -> int:
    """Get the daily sending limit for a given warming day."""
    for start, end, limit in WARMING_SCHEDULE:
        if start <= day <= end:
            return limit
    return float('inf')  # Past day 45: no limit


def handler(event, context):
    """Check warming status of all IPs and update quotas."""
    table = dynamodb.Table(TABLE_NAME)

    # Find all IPs in warming state
    response = table.scan(
        FilterExpression=Attr('SK').eq('DEDICATED_IP') & Attr('status').eq('warming')
    )

    for ip_item in response['Items']:
        org_id = ip_item['PK'].replace('ORG#', '')
        created_at = ip_item['created_at']
        warming_day = _calculate_warming_day(created_at)

        if warming_day > 45:
            # Warming complete -- move to production pool
            _complete_warming(org_id, ip_item)
            continue

        daily_limit = get_warming_limit(warming_day)

        # Update the sending quota for this org's configuration set
        _update_sending_quota(org_id, daily_limit)

        # Log warming progress
        cloudwatch = boto3.client('cloudwatch')
        cloudwatch.put_metric_data(
            Namespace='AgentMail/IPWarming',
            MetricData=[{
                'MetricName': 'WarmingDay',
                'Value': warming_day,
                'Dimensions': [
                    {'Name': 'OrgId', 'Value': org_id},
                    {'Name': 'IP', 'Value': ip_item.get('ip_address', 'pending')}
                ]
            }]
        )


def _complete_warming(org_id: str, ip_item: dict):
    """Move IP from warming pool to production pool."""
    ip_address = ip_item.get('ip_address')

    if ip_address and ip_address != 'pending':
        ses_v2.put_dedicated_ip_in_pool(
            Ip=ip_address,
            DestinationPoolName='agentmail-premium'
        )

    # Update DynamoDB
    table = dynamodb.Table(TABLE_NAME)
    table.update_item(
        Key={'PK': ip_item['PK'], 'SK': 'DEDICATED_IP'},
        UpdateExpression='SET #status = :status, pool = :pool, warmed_at = :now',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={
            ':status': 'active',
            ':pool': 'agentmail-premium',
            ':now': int(time.time() * 1000)
        }
    )

    # Update configuration set to use premium pool
    ses_v2.put_configuration_set_delivery_options(
        ConfigurationSetName=f'agentmail-{org_id}',
        TlsPolicy='REQUIRE',
        SendingPoolName='agentmail-premium'
    )
```

### Volume Distribution During Warming

During warming, excess volume (above the daily limit) should be routed to the shared pool:

```python
def route_email_during_warming(org_id: str, daily_sent_count: int, warming_limit: int):
    """
    Route email to the appropriate pool based on warming status.

    If the org is in warming and has exceeded the daily limit on the
    dedicated IP, overflow to the shared pool.
    """
    if daily_sent_count < warming_limit:
        return f'agentmail-warming'  # Send via warming IP
    else:
        return 'agentmail-standard'  # Overflow to shared dedicated pool
```

---

## SES Managed Warming with VDM

SES offers managed warming through Virtual Deliverability Manager (VDM). When an IP pool's `ScalingMode` is set to `MANAGED`, SES automatically handles the warming schedule.

### VDM-Managed Dedicated IPs

```python
# Create a managed IP pool -- SES handles warming automatically
ses_v2.create_dedicated_ip_pool(
    PoolName='agentmail-managed-warming',
    ScalingMode='MANAGED',
    Tags=[{'Key': 'managed_by', 'Value': 'agentmail'}]
)
```

**How managed warming works:**
1. SES allocates IPs to the pool based on your sending volume
2. SES automatically adjusts the volume sent through each IP
3. During warming, SES routes overflow through shared IPs
4. SES monitors bounce/complaint rates and adjusts pace
5. No manual warming schedule needed

**Pricing for managed IPs:**
- $0 for the first 10,000 messages/month (per IP)
- Standard SES pricing applies for messages sent
- No per-IP monthly charge (unlike standard dedicated IPs at $24.95/mo)
- VDM charges of $0.07 per 1,000 messages apply

### When to Use Managed vs Manual

| Scenario | Recommendation |
|---|---|
| New platform, unpredictable volume | Managed (VDM handles everything) |
| Enterprise tenant, known volume ramp | Manual (more control) |
| Standard tier, shared dedicated pool | Managed (simpler ops) |
| High-volume transactional sending | Manual (predictable, optimized) |
| Budget-sensitive | Managed (no per-IP charge) |

---

## Per-Configuration-Set Sending Quotas

SES allows setting sending quotas at the configuration set level, enabling per-tenant volume control independent of the account-level quota.

```python
def set_tenant_sending_quota(org_id: str, tier: str, warming_day: int = None):
    """Set the daily sending quota for a tenant's configuration set."""

    base_quotas = {
        'free': 200,
        'standard': 10_000,
        'premium': 50_000,
        'enterprise': 200_000,
    }

    daily_quota = base_quotas.get(tier, 200)

    # If in warming, cap at the warming schedule limit
    if warming_day is not None:
        warming_limit = get_warming_limit(warming_day)
        daily_quota = min(daily_quota, warming_limit)

    # SES doesn't have per-configuration-set quotas natively.
    # We implement this in the application layer via Redis counters.
    redis_client.set(
        f'quota:daily:{org_id}',
        daily_quota,
        ex=86400  # Expire after 24 hours
    )

    return daily_quota
```

Note: SES does not natively support per-configuration-set sending quotas. The account-level quota applies globally. We enforce per-tenant quotas in the application layer using Redis counters checked before enqueueing to SQS.

---

## Virtual Deliverability Manager (VDM)

VDM is an SES feature that provides a deliverability dashboard, engagement metrics, and automated optimizations. AgentMail enables VDM at the account level and per configuration set.

### Account-Level VDM Configuration

```python
def enable_vdm():
    """Enable Virtual Deliverability Manager at the account level."""
    ses_v2.put_account_vdm_attributes(
        VdmAttributes={
            'VdmEnabled': 'ENABLED',
            'DashboardAttributes': {
                'EngagementMetrics': 'ENABLED'
            },
            'GuardianAttributes': {
                'OptimizedSharedDelivery': 'ENABLED'
            }
        }
    )
```

### Per-Configuration-Set VDM

```python
def configure_vdm_for_config_set(config_set_name: str):
    """Enable VDM features on a configuration set."""
    ses_v2.put_configuration_set_vdm_options(
        ConfigurationSetName=config_set_name,
        VdmOptions={
            'DashboardOptions': {
                'EngagementMetrics': 'ENABLED'
            },
            'GuardianOptions': {
                'OptimizedSharedDelivery': 'ENABLED'
            }
        }
    )
```

### VDM Dashboard Metrics

VDM provides these metrics through the SES console and API:

| Metric | Description | Healthy Range |
|---|---|---|
| Delivery rate | % of emails successfully delivered | >95% |
| Bounce rate | % of emails that bounced | <5% |
| Complaint rate | % of emails reported as spam | <0.1% |
| Open rate | % of delivered emails opened | Varies by use case |
| Click rate | % of delivered emails with clicks | Varies by use case |
| Transient bounce rate | % of temporary delivery failures | <10% |
| Inbox placement | Estimated % landing in inbox vs spam | >90% |

### Querying VDM Data Programmatically

```python
def get_vdm_deliverability_stats(config_set_name: str, days: int = 7):
    """Fetch deliverability statistics from VDM."""

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    # Get ISP-level insights
    response = ses_v2.batch_get_metric_data(
        Queries=[
            {
                'Id': 'delivery_rate',
                'Namespace': 'VDM',
                'Metric': 'DELIVERY',
                'Dimensions': {
                    'CONFIGURATION_SET': config_set_name
                },
                'StartDate': start_date,
                'EndDate': end_date
            },
            {
                'Id': 'bounce_rate',
                'Namespace': 'VDM',
                'Metric': 'PERMANENT_BOUNCE',
                'Dimensions': {
                    'CONFIGURATION_SET': config_set_name
                },
                'StartDate': start_date,
                'EndDate': end_date
            },
            {
                'Id': 'complaint_rate',
                'Namespace': 'VDM',
                'Metric': 'COMPLAINT',
                'Dimensions': {
                    'CONFIGURATION_SET': config_set_name
                },
                'StartDate': start_date,
                'EndDate': end_date
            },
            {
                'Id': 'open_rate',
                'Namespace': 'VDM',
                'Metric': 'OPEN',
                'Dimensions': {
                    'CONFIGURATION_SET': config_set_name
                },
                'StartDate': start_date,
                'EndDate': end_date
            }
        ]
    )

    return {r['Id']: r['Values'] for r in response['Results']}
```

### VDM Cost

| Component | Rate |
|---|---|
| VDM base | $0 (included with SES) |
| Engagement metrics (opens/clicks) | $0.07 per 1,000 messages |
| Guardian (optimized delivery) | $0 (included with VDM) |

At 10M messages/month: 10,000 * $0.07 = **$700/month** for VDM engagement tracking.

---

## Reputation Monitoring

### Key Metrics

| Metric | Warning Threshold | Danger Threshold | SES Action |
|---|---|---|---|
| Bounce rate | 3% | 5% | Account review at 5%, suspension at 10% |
| Complaint rate | 0.05% | 0.1% | Account review at 0.1%, suspension at 0.5% |
| Hard bounce rate | 2% | 3% | Immediate suppression list entry |
| Soft bounce rate | 5% | 10% | SES automatic retry, then suppress |

### CloudWatch Metrics from SES

SES publishes these metrics to CloudWatch automatically:

```python
# SES metrics available in CloudWatch under the "AWS/SES" namespace:

METRICS = {
    'Send':             'Number of send API calls',
    'Delivery':         'Successful deliveries',
    'Bounce':           'Total bounces',
    'Complaint':        'Spam complaints',
    'Reject':           'Rejections (virus, suppression list)',
    'Open':             'Email opens (VDM)',
    'Click':            'Link clicks (VDM)',
    'RenderingFailure': 'Template rendering failures',
}

# Dimensions available:
# - ses:configuration-set (per org)
# - ses:caller-identity (IAM identity)
# - ses:from-domain (sending domain)
# - ses:outgoing-ip (dedicated IP)
```

### Real-Time Rate Computation

```python
"""
Lambda: reputation-monitor
Triggered by: EventBridge rule (every 1 minute)
"""

import boto3
from datetime import datetime, timedelta

cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')


def handler(event, context):
    """Compute real-time bounce and complaint rates per tenant."""

    # Get list of active configuration sets (one per org)
    orgs = _get_active_orgs()

    for org_id, config_set in orgs:
        now = datetime.utcnow()

        # Get metrics for the last 1 hour (rolling window)
        sends = _get_metric_sum('Send', config_set, now, hours=1)
        bounces = _get_metric_sum('Bounce', config_set, now, hours=1)
        complaints = _get_metric_sum('Complaint', config_set, now, hours=1)

        if sends == 0:
            continue

        bounce_rate = bounces / sends
        complaint_rate = complaints / sends

        # Publish computed rates as custom metrics
        cloudwatch.put_metric_data(
            Namespace='AgentMail/Reputation',
            MetricData=[
                {
                    'MetricName': 'BounceRate',
                    'Value': bounce_rate * 100,  # As percentage
                    'Unit': 'Percent',
                    'Timestamp': now,
                    'Dimensions': [
                        {'Name': 'OrgId', 'Value': org_id},
                        {'Name': 'ConfigurationSet', 'Value': config_set}
                    ]
                },
                {
                    'MetricName': 'ComplaintRate',
                    'Value': complaint_rate * 100,
                    'Unit': 'Percent',
                    'Timestamp': now,
                    'Dimensions': [
                        {'Name': 'OrgId', 'Value': org_id},
                        {'Name': 'ConfigurationSet', 'Value': config_set}
                    ]
                }
            ]
        )

        # Check thresholds and take action
        if complaint_rate >= 0.001:  # 0.1%
            _suspend_tenant(org_id, 'complaint_rate_exceeded', complaint_rate)
        elif complaint_rate >= 0.0005:  # 0.05%
            _throttle_tenant(org_id, 'complaint_rate_warning', complaint_rate)

        if bounce_rate >= 0.05:  # 5%
            _suspend_tenant(org_id, 'bounce_rate_exceeded', bounce_rate)
        elif bounce_rate >= 0.03:  # 3%
            _throttle_tenant(org_id, 'bounce_rate_warning', bounce_rate)


def _get_metric_sum(metric_name: str, config_set: str, now: datetime, hours: int) -> float:
    """Get sum of a SES metric for a configuration set over a time window."""
    response = cloudwatch.get_metric_statistics(
        Namespace='AWS/SES',
        MetricName=metric_name,
        Dimensions=[
            {'Name': 'ses:configuration-set', 'Value': config_set}
        ],
        StartTime=now - timedelta(hours=hours),
        EndTime=now,
        Period=3600,
        Statistics=['Sum']
    )
    datapoints = response.get('Datapoints', [])
    return sum(dp['Sum'] for dp in datapoints)
```

---

## Per-Tenant Reputation Isolation

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Per-Tenant Reputation System                    │
│                                                                    │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────┐  │
│  │ Pre-Send     │    │ Real-Time    │    │ Automated Actions   │  │
│  │ Checks       │    │ Monitoring   │    │                     │  │
│  │              │    │              │    │                     │  │
│  │ • Content    │    │ • Bounce     │    │ • Throttle at       │  │
│  │   scanning   │    │   rate/min   │    │   warning threshold │  │
│  │ • Suppression│    │ • Complaint  │    │ • Suspend at        │  │
│  │   list check │    │   rate/min   │    │   danger threshold  │  │
│  │ • Rate limit │    │ • Send       │    │ • Move to quarantine│  │
│  │   check      │    │   volume     │    │   IP pool           │  │
│  │ • Domain     │    │ • Per-ISP    │    │ • Notify tenant     │  │
│  │   verified?  │    │   breakdown  │    │ • Notify ops team   │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬──────────┘  │
│         │                   │                       │              │
│         ▼                   ▼                       ▼              │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    DynamoDB: Tenant Reputation State          │ │
│  │                                                              │ │
│  │  PK: ORG#{org_id}  SK: REPUTATION                           │ │
│  │  {                                                           │ │
│  │    status: "active" | "throttled" | "suspended",             │ │
│  │    bounce_rate_1h: 0.02,                                     │ │
│  │    complaint_rate_1h: 0.0003,                                │ │
│  │    sends_today: 4523,                                        │ │
│  │    bounces_today: 45,                                        │ │
│  │    complaints_today: 2,                                      │ │
│  │    ip_pool: "agentmail-standard",                            │ │
│  │    throttle_factor: 1.0,     // 1.0 = no throttle            │ │
│  │    last_throttle_at: null,                                   │ │
│  │    last_suspend_at: null,                                    │ │
│  │    content_scan_enabled: true                                │ │
│  │  }                                                           │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### Automatic Throttling

When a tenant's bounce or complaint rate approaches danger thresholds, we progressively reduce their sending rate:

```python
THROTTLE_LEVELS = {
    # (bounce_rate_threshold, complaint_rate_threshold): throttle_factor
    (0.02, 0.0003): 0.75,   # 75% of normal rate
    (0.03, 0.0005): 0.50,   # 50% of normal rate
    (0.04, 0.0008): 0.25,   # 25% of normal rate
    (0.05, 0.001):  0.0,    # Suspended (0% = no sending)
}


def compute_throttle_factor(bounce_rate: float, complaint_rate: float) -> float:
    """
    Compute the sending throttle factor based on current rates.

    Returns a float between 0.0 (suspended) and 1.0 (no throttle).
    """
    factor = 1.0

    for (bounce_threshold, complaint_threshold), level_factor in THROTTLE_LEVELS.items():
        if bounce_rate >= bounce_threshold or complaint_rate >= complaint_threshold:
            factor = min(factor, level_factor)

    return factor


def _throttle_tenant(org_id: str, reason: str, rate: float):
    """Apply throttling to a tenant."""
    table = dynamodb.Table(TABLE_NAME)
    now_ms = int(time.time() * 1000)

    factor = compute_throttle_factor(
        bounce_rate=rate if 'bounce' in reason else 0,
        complaint_rate=rate if 'complaint' in reason else 0
    )

    table.update_item(
        Key={'PK': f'ORG#{org_id}', 'SK': 'REPUTATION'},
        UpdateExpression=(
            'SET #status = :status, '
            'throttle_factor = :factor, '
            'last_throttle_at = :now, '
            'throttle_reason = :reason'
        ),
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={
            ':status': 'throttled',
            ':factor': factor,
            ':now': now_ms,
            ':reason': reason
        }
    )

    # Update Redis cache for fast lookup during send
    redis_client.hset(f'reputation:{org_id}', mapping={
        'status': 'throttled',
        'throttle_factor': str(factor)
    })
    redis_client.expire(f'reputation:{org_id}', 300)  # 5 min cache

    # Notify tenant via webhook/event
    kinesis.put_record(
        StreamName=KINESIS_STREAM,
        Data=json.dumps({
            'eventType': 'account.throttled',
            'orgId': org_id,
            'data': {
                'reason': reason,
                'throttle_factor': factor,
                'current_rate': rate
            }
        }),
        PartitionKey=org_id
    )


def _suspend_tenant(org_id: str, reason: str, rate: float):
    """Suspend sending for a tenant. Requires manual review to reinstate."""
    table = dynamodb.Table(TABLE_NAME)
    now_ms = int(time.time() * 1000)

    # Move tenant to quarantine pool
    try:
        ses_v2.put_configuration_set_delivery_options(
            ConfigurationSetName=f'agentmail-{org_id}',
            SendingPoolName='agentmail-quarantine'
        )
    except Exception:
        pass

    # Disable sending on the configuration set
    ses_v2.put_configuration_set_sending_options(
        ConfigurationSetName=f'agentmail-{org_id}',
        SendingEnabled=False
    )

    table.update_item(
        Key={'PK': f'ORG#{org_id}', 'SK': 'REPUTATION'},
        UpdateExpression=(
            'SET #status = :status, '
            'throttle_factor = :zero, '
            'last_suspend_at = :now, '
            'suspend_reason = :reason'
        ),
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={
            ':status': 'suspended',
            ':zero': 0.0,
            ':now': now_ms,
            ':reason': reason
        }
    )

    # Update Redis
    redis_client.hset(f'reputation:{org_id}', mapping={
        'status': 'suspended',
        'throttle_factor': '0'
    })

    # Alert operations team
    sns = boto3.client('sns')
    sns.publish(
        TopicArn=f'arn:aws:sns:us-east-1:{ACCOUNT_ID}:agentmail-ops-alerts',
        Subject=f'[CRITICAL] Tenant {org_id} suspended for {reason}',
        Message=json.dumps({
            'org_id': org_id,
            'reason': reason,
            'rate': rate,
            'action': 'suspended',
            'requires_manual_review': True
        })
    )
```

### Content Scanning Before Sending

For tenants on shared IPs or in their first 30 days, we scan outbound content:

```python
def scan_outbound_content(message: dict, org_id: str) -> dict:
    """
    Scan outbound message content for spam indicators.

    Returns: {'allowed': bool, 'score': float, 'flags': list}
    """
    flags = []
    score = 0.0

    subject = message.get('subject', '')
    text_body = message.get('text_body', '')
    html_body = message.get('html_body', '')

    full_text = f'{subject} {text_body}'.lower()

    # ── Rule 1: Spam keyword density ─────────────────────────────────
    SPAM_KEYWORDS = [
        'free money', 'click here now', 'limited time offer',
        'act now', 'congratulations you won', 'nigerian prince',
        'wire transfer', 'social security number', 'lottery winner',
        'no obligation', 'risk free', 'guaranteed income',
    ]
    keyword_hits = sum(1 for kw in SPAM_KEYWORDS if kw in full_text)
    if keyword_hits >= 3:
        flags.append('high_spam_keyword_density')
        score += 0.3

    # ── Rule 2: Suspicious URL patterns ──────────────────────────────
    import re
    urls = re.findall(r'https?://[^\s<>"]+', html_body or text_body)
    for url in urls:
        if re.search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', url):
            flags.append('ip_address_url')
            score += 0.2
        if len(url) > 200:
            flags.append('excessively_long_url')
            score += 0.1

    # ── Rule 3: HTML/text ratio ──────────────────────────────────────
    if html_body and not text_body:
        # HTML-only emails with no text alternative are suspicious
        flags.append('html_only_no_text')
        score += 0.1

    # ── Rule 4: Excessive recipients ─────────────────────────────────
    total_recipients = len(message.get('to', [])) + len(message.get('cc', []))
    if total_recipients > 50:
        flags.append('excessive_recipients')
        score += 0.2

    # ── Decision ─────────────────────────────────────────────────────
    allowed = score < 0.5

    return {
        'allowed': allowed,
        'score': score,
        'flags': flags
    }
```

### Tenant Identity Verification Requirements

Before a tenant can send from a domain, they must:

1. **Verify domain ownership** (DKIM verification via SES)
2. **Set up SPF** (TXT record including `amazonses.com`)
3. **Configure DMARC** (at minimum `p=none`)
4. **Verify a human contact** (email to `postmaster@` or `admin@` the domain)
5. **Pass initial content review** (first 100 emails are held for automated scanning)

```python
def check_tenant_send_readiness(org_id: str) -> dict:
    """Check if a tenant meets all requirements for sending."""
    table = dynamodb.Table(TABLE_NAME)

    checks = {
        'domain_verified': False,
        'spf_configured': False,
        'dmarc_configured': False,
        'contact_verified': False,
        'initial_review_passed': False,
        'ready_to_send': False
    }

    # Check domains
    domains = table.query(
        KeyConditionExpression=(
            Key('PK').eq(f'ORG#{org_id}') &
            Key('SK').begins_with('DOM#')
        )
    )

    for domain in domains.get('Items', []):
        if domain['status'] in ('verified', 'verified_send_only'):
            checks['domain_verified'] = True
            if domain.get('spf_status') == 'verified':
                checks['spf_configured'] = True
            if domain.get('dmarc_status') == 'verified':
                checks['dmarc_configured'] = True

    # Check org settings
    org = table.get_item(
        Key={'PK': f'ORG#{org_id}', 'SK': 'META'}
    ).get('Item', {})

    checks['contact_verified'] = org.get('contact_verified', False)
    checks['initial_review_passed'] = org.get('initial_review_passed', False)

    checks['ready_to_send'] = all([
        checks['domain_verified'],
        checks['spf_configured'],
        # DMARC is recommended but not required
        checks['contact_verified'] or checks['initial_review_passed']
    ])

    return checks
```

---

## Suppression List Management

### Two-Level Suppression

AgentMail maintains suppression lists at two levels:

1. **SES account-level suppression list** -- Managed by AWS, automatically populated on hard bounces and complaints. Applies to all sending from the account.
2. **Per-tenant suppression list** -- Managed by AgentMail in DynamoDB. Tenants can also manage their own lists via API.

### SES Account-Level Suppression

```python
# SES automatically adds addresses to the suppression list on:
# - Hard bounces (permanent delivery failure)
# - Complaints (recipient marked as spam)

# Check if an address is suppressed
def is_ses_suppressed(address: str) -> bool:
    try:
        ses_v2.get_suppressed_destination(EmailAddress=address)
        return True
    except ses_v2.exceptions.NotFoundException:
        return False

# Manually add to SES suppression list
def add_ses_suppression(address: str, reason: str):
    ses_v2.put_suppressed_destination(
        EmailAddress=address,
        Reason='BOUNCE' if reason == 'bounce' else 'COMPLAINT'
    )

# Remove from SES suppression list (use carefully!)
def remove_ses_suppression(address: str):
    ses_v2.delete_suppressed_destination(EmailAddress=address)

# List all suppressed addresses
def list_ses_suppressions(reason: str = None, start_date=None, end_date=None):
    paginator = ses_v2.get_paginator('list_suppressed_destinations')
    params = {}
    if reason:
        params['Reasons'] = [reason]
    if start_date:
        params['StartDate'] = start_date
    if end_date:
        params['EndDate'] = end_date

    for page in paginator.paginate(**params):
        for item in page['SuppressedDestinationSummaries']:
            yield {
                'address': item['EmailAddress'],
                'reason': item['Reason'],
                'created_at': item['CreatedTimestamp'],
                'last_update': item['LastUpdateTime']
            }
```

### Per-Tenant Suppression (DynamoDB)

```python
# DynamoDB schema for per-tenant suppression:
# PK: ORG#{org_id}
# SK: SUPPRESS#{email_address}
# Attributes: reason, source, created_at, ttl

def add_tenant_suppression(org_id: str, address: str, reason: str, source: str):
    """Add an address to a tenant's suppression list."""
    table = dynamodb.Table(TABLE_NAME)
    table.put_item(Item={
        'PK': f'ORG#{org_id}',
        'SK': f'SUPPRESS#{address.lower()}',
        'email_address': address.lower(),
        'reason': reason,       # 'bounce', 'complaint', 'manual', 'unsubscribe'
        'source': source,       # 'ses_event', 'api', 'list_unsubscribe'
        'created_at': int(time.time() * 1000),
        # Optional TTL: auto-remove after 1 year for bounces
        # (addresses may become valid again)
        'ttl': int(time.time()) + (365 * 86400) if reason == 'bounce' else None
    })


def remove_tenant_suppression(org_id: str, address: str):
    """Remove an address from a tenant's suppression list."""
    table = dynamodb.Table(TABLE_NAME)
    table.delete_item(
        Key={
            'PK': f'ORG#{org_id}',
            'SK': f'SUPPRESS#{address.lower()}'
        }
    )


def check_tenant_suppression(org_id: str, address: str) -> dict | None:
    """Check if an address is on a tenant's suppression list."""
    table = dynamodb.Table(TABLE_NAME)
    response = table.get_item(
        Key={
            'PK': f'ORG#{org_id}',
            'SK': f'SUPPRESS#{address.lower()}'
        }
    )
    return response.get('Item')


def check_all_suppression(org_id: str, address: str) -> tuple[bool, str]:
    """
    Check both SES and tenant suppression lists.
    Returns (is_suppressed, reason).
    """
    # Check tenant list first (cheaper, no API call)
    tenant_supp = check_tenant_suppression(org_id, address)
    if tenant_supp:
        return True, f'tenant:{tenant_supp["reason"]}'

    # Check SES account list
    if is_ses_suppressed(address):
        return True, 'ses_account'

    return False, ''
```

### API for Tenant Suppression Management

```
GET    /v1/suppressions                 → List suppressed addresses for this org
POST   /v1/suppressions                 → Add address to suppression list
DELETE /v1/suppressions/{address}        → Remove address from suppression list
GET    /v1/suppressions/{address}        → Check if address is suppressed
```

---

## Feedback Loops and ISP Relationships

### SES Feedback Loop Integration

SES automatically processes feedback loops (FBLs) from major ISPs. When a recipient marks an email as spam, the ISP notifies SES, and SES publishes a `Complaint` event to our SNS topic.

ISPs with feedback loop support:

| ISP | FBL Type | Format |
|---|---|---|
| Gmail | XARF + postmaster tools | Custom (via VDM) |
| Yahoo/AOL | CFL (Complaint Feedback Loop) | ARF |
| Microsoft (Outlook/Hotmail) | JMRP/SNDS | ARF |
| Comcast | FBL | ARF |
| Apple (iCloud) | FBL | ARF |

### Postmaster Addresses

We maintain standard postmaster addresses for ISP communication:

```
postmaster@agentmail.dev    → Ops team email
abuse@agentmail.dev         → Abuse handling team
dmarc-reports@agentmail.dev → DMARC aggregate report receiver
```

These are actual inboxes on the platform that route to the operations team, not AI agent inboxes.

### DMARC Aggregate Report Processing

```python
"""
Lambda: dmarc-report-processor
Triggered by: Inbound email to dmarc-reports@agentmail.dev
"""

import xml.etree.ElementTree as ET
import gzip
import zipfile
import io


def process_dmarc_report(raw_mime_bytes: bytes):
    """
    Parse DMARC aggregate reports (XML, often gzipped/zipped).

    Extracts per-source-IP authentication results and stores
    them for monitoring our sending IP reputation.
    """
    # Parse MIME to extract attachment
    msg = email.message_from_bytes(raw_mime_bytes)
    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue

        data = part.get_payload(decode=True)

        # Decompress if needed
        if filename.endswith('.gz'):
            data = gzip.decompress(data)
        elif filename.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                data = zf.read(zf.namelist()[0])

        # Parse XML report
        root = ET.fromstring(data)

        report_org = root.findtext('.//report_metadata/org_name')
        report_id = root.findtext('.//report_metadata/report_id')

        for record in root.findall('.//record'):
            source_ip = record.findtext('.//row/source_ip')
            count = int(record.findtext('.//row/count', '0'))
            disposition = record.findtext('.//row/policy_evaluated/disposition')
            dkim_result = record.findtext('.//row/policy_evaluated/dkim')
            spf_result = record.findtext('.//row/policy_evaluated/spf')
            domain = record.findtext('.//identifiers/header_from')

            # Store for analysis
            _store_dmarc_result({
                'report_org': report_org,
                'report_id': report_id,
                'source_ip': source_ip,
                'count': count,
                'disposition': disposition,
                'dkim': dkim_result,
                'spf': spf_result,
                'domain': domain
            })

            # Alert if our IPs are failing DMARC
            if dkim_result == 'fail' or spf_result == 'fail':
                _alert_dmarc_failure(source_ip, domain, dkim_result, spf_result)
```

---

## CloudWatch Alarms for Deliverability

### Alarm Definitions

```python
"""
CDK construct for deliverability alarms.
"""

from aws_cdk import (
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
)


def create_deliverability_alarms(stack, ops_topic: sns.Topic):
    """Create CloudWatch alarms for email deliverability monitoring."""

    # ── Account-Level Bounce Rate ────────────────────────────────────
    cw.Alarm(stack, 'AccountBounceRate',
        alarm_name='agentmail-account-bounce-rate-high',
        metric=cw.Metric(
            namespace='AWS/SES',
            metric_name='Reputation.BounceRate',
            statistic='Average',
            period=Duration.minutes(5)
        ),
        threshold=0.05,  # 5%
        evaluation_periods=3,
        comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        alarm_description='Account-level bounce rate exceeds 5%. SES may suspend sending.',
        actions_enabled=True,
    ).add_alarm_action(cw_actions.SnsAction(ops_topic))

    # ── Account-Level Complaint Rate ─────────────────────────────────
    cw.Alarm(stack, 'AccountComplaintRate',
        alarm_name='agentmail-account-complaint-rate-high',
        metric=cw.Metric(
            namespace='AWS/SES',
            metric_name='Reputation.ComplaintRate',
            statistic='Average',
            period=Duration.minutes(5)
        ),
        threshold=0.001,  # 0.1%
        evaluation_periods=3,
        comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        alarm_description='Account-level complaint rate exceeds 0.1%. SES may suspend sending.',
    ).add_alarm_action(cw_actions.SnsAction(ops_topic))

    # ── Per-Tenant Bounce Rate (custom metric) ───────────────────────
    # This alarm is created dynamically per tenant -- shown as template
    cw.Alarm(stack, 'TenantBounceRateTemplate',
        alarm_name='agentmail-tenant-bounce-rate-${OrgId}',
        metric=cw.Metric(
            namespace='AgentMail/Reputation',
            metric_name='BounceRate',
            dimensions_map={'OrgId': '${OrgId}'},
            statistic='Average',
            period=Duration.minutes(5)
        ),
        threshold=3.0,  # 3% (warning)
        evaluation_periods=2,
        comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        alarm_description='Tenant bounce rate exceeds 3%. Automatic throttling applied.',
    )

    # ── Send Failures (DLQ depth) ────────────────────────────────────
    cw.Alarm(stack, 'SendDLQDepth',
        alarm_name='agentmail-send-dlq-depth',
        metric=cw.Metric(
            namespace='AWS/SQS',
            metric_name='ApproximateNumberOfMessagesVisible',
            dimensions_map={'QueueName': 'agentmail-send-dlq'},
            statistic='Sum',
            period=Duration.minutes(5)
        ),
        threshold=10,
        evaluation_periods=1,
        comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        alarm_description='Send DLQ has >10 messages. Indicates persistent send failures.',
    ).add_alarm_action(cw_actions.SnsAction(ops_topic))

    # ── Inbound Processing Failures ──────────────────────────────────
    cw.Alarm(stack, 'InboundProcessingErrors',
        alarm_name='agentmail-inbound-processing-errors',
        metric=cw.Metric(
            namespace='AWS/Lambda',
            metric_name='Errors',
            dimensions_map={'FunctionName': 'inbound-router'},
            statistic='Sum',
            period=Duration.minutes(5)
        ),
        threshold=5,
        evaluation_periods=2,
        comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        alarm_description='Inbound router Lambda has >5 errors in 5 minutes.',
    ).add_alarm_action(cw_actions.SnsAction(ops_topic))

    # ── Daily Send Volume Approaching Quota ──────────────────────────
    cw.Alarm(stack, 'DailySendVolumeHigh',
        alarm_name='agentmail-daily-send-volume-high',
        metric=cw.Metric(
            namespace='AWS/SES',
            metric_name='Send',
            statistic='Sum',
            period=Duration.hours(1)
        ),
        threshold=40000,  # 80% of 50K default quota
        evaluation_periods=1,
        comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        alarm_description='Approaching daily SES sending quota. Consider requesting increase.',
    ).add_alarm_action(cw_actions.SnsAction(ops_topic))

    # ── SES Sending Disabled ─────────────────────────────────────────
    # This is the nuclear alarm -- SES has suspended our account
    cw.Alarm(stack, 'SESSendingDisabled',
        alarm_name='agentmail-ses-sending-disabled',
        metric=cw.Metric(
            namespace='AgentMail/Health',
            metric_name='SESSendingEnabled',
            statistic='Minimum',
            period=Duration.minutes(1)
        ),
        threshold=1,
        evaluation_periods=1,
        comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD,
        alarm_description='CRITICAL: SES sending has been disabled. All email sending is blocked.',
        treat_missing_data=cw.TreatMissingData.BREACHING,
    ).add_alarm_action(cw_actions.SnsAction(ops_topic))
```

### SES Account Status Health Check

```python
"""
Lambda: ses-health-check
Triggered by: EventBridge rule (every 1 minute)
"""

def handler(event, context):
    """Check SES account health and publish custom metrics."""
    ses_v2 = boto3.client('sesv2')
    cloudwatch = boto3.client('cloudwatch')

    # Get account details
    account = ses_v2.get_account()

    sending_enabled = account['SendingEnabled']
    enforcement_status = account.get('EnforcementStatus', 'HEALTHY')

    # Get send quota
    send_quota = account['SendQuota']
    max_24h = send_quota['Max24HourSend']
    sent_24h = send_quota['SentLast24Hours']
    max_send_rate = send_quota['MaxSendRate']

    usage_percent = (sent_24h / max_24h * 100) if max_24h > 0 else 0

    # Publish custom metrics
    cloudwatch.put_metric_data(
        Namespace='AgentMail/Health',
        MetricData=[
            {
                'MetricName': 'SESSendingEnabled',
                'Value': 1 if sending_enabled else 0,
                'Unit': 'None'
            },
            {
                'MetricName': 'SESQuotaUsagePercent',
                'Value': usage_percent,
                'Unit': 'Percent'
            },
            {
                'MetricName': 'SESSentLast24Hours',
                'Value': sent_24h,
                'Unit': 'Count'
            },
            {
                'MetricName': 'SESMaxSendRate',
                'Value': max_send_rate,
                'Unit': 'Count/Second'
            }
        ]
    )

    # Alert if account is under review or suspended
    if enforcement_status != 'HEALTHY':
        sns = boto3.client('sns')
        sns.publish(
            TopicArn=f'arn:aws:sns:us-east-1:{ACCOUNT_ID}:agentmail-ops-alerts',
            Subject=f'[CRITICAL] SES Account Status: {enforcement_status}',
            Message=json.dumps({
                'enforcement_status': enforcement_status,
                'sending_enabled': sending_enabled,
                'quota_usage_percent': usage_percent,
                'sent_last_24h': sent_24h,
                'max_24h': max_24h
            })
        )
```

### Alarm Dashboard

```python
# CloudWatch Dashboard definition (JSON)
DELIVERABILITY_DASHBOARD = {
    "widgets": [
        {
            "type": "metric",
            "properties": {
                "title": "Account Reputation",
                "metrics": [
                    ["AWS/SES", "Reputation.BounceRate", {"label": "Bounce Rate", "color": "#d62728"}],
                    ["AWS/SES", "Reputation.ComplaintRate", {"label": "Complaint Rate", "color": "#ff7f0e"}]
                ],
                "period": 300,
                "stat": "Average",
                "yAxis": {"left": {"min": 0, "max": 0.1}},
                "annotations": {
                    "horizontal": [
                        {"value": 0.05, "label": "Bounce Danger", "color": "#d62728"},
                        {"value": 0.03, "label": "Bounce Warning", "color": "#ff7f0e"},
                        {"value": 0.001, "label": "Complaint Danger", "color": "#d62728"},
                        {"value": 0.0005, "label": "Complaint Warning", "color": "#ff7f0e"}
                    ]
                }
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "Send Volume (Hourly)",
                "metrics": [
                    ["AWS/SES", "Send", {"stat": "Sum", "period": 3600}],
                    ["AWS/SES", "Delivery", {"stat": "Sum", "period": 3600}],
                    ["AWS/SES", "Bounce", {"stat": "Sum", "period": 3600}],
                    ["AWS/SES", "Complaint", {"stat": "Sum", "period": 3600}]
                ]
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "Per-Tenant Bounce Rates (Top 10)",
                "metrics": [
                    ["AgentMail/Reputation", "BounceRate", "OrgId", "org_001"],
                    ["AgentMail/Reputation", "BounceRate", "OrgId", "org_002"],
                    ["AgentMail/Reputation", "BounceRate", "OrgId", "org_003"]
                ],
                "period": 300,
                "stat": "Average"
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "SES Quota Usage",
                "metrics": [
                    ["AgentMail/Health", "SESQuotaUsagePercent", {"label": "% Used"}],
                    ["AgentMail/Health", "SESSentLast24Hours", {"label": "Sent 24h", "yAxis": "right"}]
                ]
            }
        }
    ]
}
```
