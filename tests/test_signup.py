"""Tests for the signup Lambda handler."""

import json

import pytest


def test_signup_creates_otp(aws_env):
    """Test that signup stores OTP and returns 201."""
    from signup.handler import handler, _otp_store

    event = {
        "httpMethod": "POST",
        "path": "/v1/agent/signup",
        "body": json.dumps({"email": "test@example.com"}),
    }

    result = handler(event, None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["email"] == "test@example.com"
    assert body["message"] == "Verification code sent"
    assert "test@example.com" in _otp_store


def test_verify_creates_org_and_key(aws_env):
    """Test that verify creates an org and API key."""
    from signup.handler import handler, _otp_store

    # First signup to get OTP
    signup_event = {
        "httpMethod": "POST",
        "path": "/v1/agent/signup",
        "body": json.dumps({"email": "verify@example.com"}),
    }
    handler(signup_event, None)

    # Get the code from the store
    code = _otp_store["verify@example.com"]

    # Verify
    verify_event = {
        "httpMethod": "POST",
        "path": "/v1/agent/verify",
        "body": json.dumps({"email": "verify@example.com", "code": code}),
    }
    result = handler(verify_event, None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])

    # Check organization
    assert "organization" in body
    org = body["organization"]
    assert org["email"] == "verify@example.com"
    assert org["tier"] == "free"
    assert org["status"] == "active"

    # Check API key
    assert "api_key" in body
    key = body["api_key"]
    assert key["key"].startswith("am_live_")
    assert key["scope"] == "org"


def test_verify_bad_code(aws_env):
    """Test that verify with wrong code returns 401."""
    from signup.handler import handler, _otp_store

    # Signup first
    signup_event = {
        "httpMethod": "POST",
        "path": "/v1/agent/signup",
        "body": json.dumps({"email": "bad@example.com"}),
    }
    handler(signup_event, None)

    # Verify with wrong code
    verify_event = {
        "httpMethod": "POST",
        "path": "/v1/agent/verify",
        "body": json.dumps({"email": "bad@example.com", "code": "000000"}),
    }

    # Make sure the code is not 000000
    if _otp_store.get("bad@example.com") == "000000":
        _otp_store["bad@example.com"] = "111111"

    result = handler(verify_event, None)
    assert result["statusCode"] == 401
