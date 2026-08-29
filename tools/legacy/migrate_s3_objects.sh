#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
#
# Orchestrates the 3 S3 bucket migrations for the FreeMail → AgentComms pivot.
#
# Usage:
#   ./tools/migrate_s3_objects.sh            # live run
#   DRY_RUN="--dry-run" ./tools/migrate_s3_objects.sh   # dry-run
#
# Prerequisites:
#   - AWS credentials configured (reads .env in repo root if present)
#   - python tools/migrate_s3_rekey.py available

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env credentials if present (avoids wrong-account fallback)
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -o allexport
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +o allexport
fi

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
SUFFIX="prod-$ACCOUNT"
DRY_RUN="${DRY_RUN:-}"

echo "==> AWS account: $ACCOUNT"
echo "==> Bucket suffix: $SUFFIX"
if [[ -n "$DRY_RUN" ]]; then
    echo "==> DRY RUN mode — no objects will be written"
fi
echo ""

echo "==> [1/3] Migrating raw-inbound (re-keying inbound/{ses_message_id} → {org_id}/{agent_id}/email/{msg_id})..."
python "$SCRIPT_DIR/migrate_s3_rekey.py" \
  --source-bucket "victorymail-raw-email" \
  --dest-bucket "agentcomms-raw-inbound-$SUFFIX" \
  --json \
  ${DRY_RUN}

echo ""
echo "==> [2/3] Migrating bodies (passthrough — same key structure)..."
python "$SCRIPT_DIR/migrate_s3_rekey.py" \
  --source-bucket "victorymail-bodies" \
  --dest-bucket "agentcomms-bodies-$SUFFIX" \
  --passthrough \
  --json \
  ${DRY_RUN}

echo ""
echo "==> [3/3] Migrating attachments (passthrough — same key structure)..."
python "$SCRIPT_DIR/migrate_s3_rekey.py" \
  --source-bucket "victorymail-attachments" \
  --dest-bucket "agentcomms-attachments-$SUFFIX" \
  --passthrough \
  --json \
  ${DRY_RUN}

echo ""
echo "==> Done."
echo ""
echo "Verify object counts:"
echo "  aws s3 ls s3://agentcomms-raw-inbound-$SUFFIX --recursive --summarize | tail -2"
echo "  aws s3 ls s3://agentcomms-bodies-$SUFFIX       --recursive --summarize | tail -2"
echo "  aws s3 ls s3://agentcomms-attachments-$SUFFIX  --recursive --summarize | tail -2"
