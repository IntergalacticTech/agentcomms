# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

from __future__ import annotations

import json
import os
from typing import Any

import boto3


class KinesisEventPublisher:
    def __init__(self, *, stream_name: str | None = None, client=None):
        self.stream_name = stream_name if stream_name is not None else os.environ.get("AGENTCOMMS_EVENT_STREAM")
        self.client = client or boto3.client("kinesis")

    def publish(self, *, event_type: str, partition_key: str, data: dict[str, Any]) -> None:
        if not self.stream_name:
            return
        self.client.put_record(
            StreamName=self.stream_name,
            PartitionKey=partition_key,
            Data=json.dumps({"type": event_type, "data": data}).encode("utf-8"),
        )

