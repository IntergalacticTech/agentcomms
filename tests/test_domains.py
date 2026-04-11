"""Tests for the Domains Lambda handler."""

import json

from domains.handler import handler


ORG_ID = "org_test123"


def _make_event(method, path="/", path_params=None, body=None, query_params=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }


def test_create_domain(aws_env):
    """Test creating a new domain."""
    event = _make_event(
        "POST",
        path="/domains",
        body={"domain": "example.com"},
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 201

    data = json.loads(resp["body"])
    assert data["domain"] == "example.com"
    assert data["status"] == "pending"
    assert "org_id" not in data  # Internal field should be stripped

    # Check DNS records
    dns = data["dns_records"]
    assert dns["mx"]["value"] == "10 inbound-smtp.us-east-1.amazonaws.com"
    assert "amazonses.com" in dns["spf"]["value"]
    assert len(dns["dkim"]) == 3
    assert dns["dkim"][0]["name"] == "s1._domainkey.example.com"
    assert dns["dkim"][0]["value"] == "s1.dkim.victorymail.dev"
    assert "DMARC1" in dns["dmarc"]["value"]


def test_create_domain_missing_field(aws_env):
    """Test creating a domain without required field."""
    event = _make_event("POST", path="/domains", body={})
    resp = handler(event, None)
    assert resp["statusCode"] == 400


def test_get_domain(aws_env):
    """Test getting a single domain."""
    # Create first
    create_event = _make_event("POST", path="/domains", body={"domain": "test.com"})
    create_resp = handler(create_event, None)
    domain = json.loads(create_resp["body"])
    domain_id = domain["id"]

    get_event = _make_event(
        "GET",
        path=f"/domains/{domain_id}",
        path_params={"id": domain_id},
    )
    resp = handler(get_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["domain"] == "test.com"


def test_list_domains(aws_env):
    """Test listing domains."""
    _make_event("POST", path="/domains", body={"domain": "a.com"})
    handler(_make_event("POST", path="/domains", body={"domain": "a.com"}), None)
    handler(_make_event("POST", path="/domains", body={"domain": "b.com"}), None)

    list_event = _make_event("GET", path="/domains")
    resp = handler(list_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert len(data["data"]) == 2


def test_verify_domain(aws_env):
    """Test starting domain verification."""
    create_resp = handler(
        _make_event("POST", path="/domains", body={"domain": "verify.com"}), None
    )
    domain = json.loads(create_resp["body"])
    domain_id = domain["id"]

    verify_event = _make_event(
        "POST",
        path=f"/domains/{domain_id}/verify",
        path_params={"id": domain_id},
    )
    resp = handler(verify_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["status"] == "verifying"


def test_delete_domain(aws_env):
    """Test hard deleting a domain."""
    create_resp = handler(
        _make_event("POST", path="/domains", body={"domain": "delete.com"}), None
    )
    domain = json.loads(create_resp["body"])
    domain_id = domain["id"]

    delete_event = _make_event(
        "DELETE",
        path=f"/domains/{domain_id}",
        path_params={"id": domain_id},
    )
    resp = handler(delete_event, None)
    assert resp["statusCode"] == 204

    # Verify gone
    get_event = _make_event("GET", path=f"/domains/{domain_id}", path_params={"id": domain_id})
    resp = handler(get_event, None)
    assert resp["statusCode"] == 404


def test_zone_file(aws_env):
    """Test getting the zone file."""
    create_resp = handler(
        _make_event("POST", path="/domains", body={"domain": "zone.com"}), None
    )
    domain = json.loads(create_resp["body"])
    domain_id = domain["id"]

    zone_event = _make_event(
        "GET",
        path=f"/domains/{domain_id}/zone-file",
        path_params={"id": domain_id},
    )
    resp = handler(zone_event, None)
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "text/dns"
    assert "zone.com" in resp["body"]
    assert "MX" in resp["body"]
    assert "CNAME" in resp["body"]


def test_update_domain_catch_all(aws_env):
    """Test updating domain catch_all_inbox_id."""
    create_resp = handler(
        _make_event("POST", path="/domains", body={"domain": "catch.com"}), None
    )
    domain = json.loads(create_resp["body"])
    domain_id = domain["id"]

    patch_event = _make_event(
        "PATCH",
        path=f"/domains/{domain_id}",
        path_params={"id": domain_id},
        body={"catch_all_inbox_id": "inbox_xyz"},
    )
    resp = handler(patch_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["catch_all_inbox_id"] == "inbox_xyz"
