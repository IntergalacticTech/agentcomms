# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/vault/kms.py
"""Thin KMS encrypt/decrypt helpers for vault secret blobs.

Stateless — no client caching.  Each call creates a fresh boto3 client so
tests can freely mock at the boto3 layer (moto or unittest.mock.patch).
"""
from __future__ import annotations

import os

import boto3

_DEFAULT_KEY_ALIAS = "alias/aws/kms"


def _client():
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    return boto3.client("kms", region_name=region)


def encrypt(plaintext: bytes, kms_key_id: str | None = None) -> tuple[bytes, str]:
    """Encrypt *plaintext* under *kms_key_id* (defaults to the account-default
    symmetric key alias ``alias/aws/kms``).

    Returns ``(ciphertext_blob, key_id_used)``.
    """
    key_id = kms_key_id or os.environ.get("AGENTCOMMS_VAULT_KMS_KEY_ID", _DEFAULT_KEY_ALIAS)
    kms = _client()
    resp = kms.encrypt(KeyId=key_id, Plaintext=plaintext)
    return resp["CiphertextBlob"], resp["KeyId"]


def decrypt(ciphertext_blob: bytes) -> bytes:
    """Decrypt *ciphertext_blob*.  The key is embedded in the ciphertext
    by KMS so no key_id argument is needed."""
    kms = _client()
    resp = kms.decrypt(CiphertextBlob=ciphertext_blob)
    return resp["Plaintext"]
