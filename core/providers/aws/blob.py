# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

from __future__ import annotations

import boto3


class S3BlobStore:
    def __init__(self, client=None):
        self.client = client or boto3.client("s3")

    def get_bytes(self, *, bucket: str, key: str) -> bytes:
        obj = self.client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()

    def put_bytes(
        self, *, bucket: str, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Store bytes at a provider-specific blob location; return the key."""
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=bucket, Key=key, Body=data, **extra)
        return key

