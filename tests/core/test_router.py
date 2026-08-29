# tests/core/test_router.py
import pytest
from core.router.address import infer_channel, AmbiguousAddressError


@pytest.mark.parametrize("address,expected", [
    ("alice@example.com", "email"),
    ("+15551234567", "sms"),
    ("slack:T123:U456", "slack"),
    ("discord:123456789:987654321", "discord"),
    ("telegram:chat:123456", "telegram"),
    ("push:apns:arn:aws:sns:us-east-1:123:app/APNS/x/endpoint/y", "push"),
    ("push:fcm:arn:aws:sns:us-east-1:123:app/FCM/x/endpoint/y", "push"),
])
def test_infer_channel_unambiguous(address, expected):
    assert infer_channel(address) == expected


def test_infer_channel_invalid_raises():
    with pytest.raises(AmbiguousAddressError):
        infer_channel("not-really-anything")


def test_infer_channel_sms_rejects_non_e164():
    with pytest.raises(AmbiguousAddressError):
        infer_channel("5551234567")  # missing '+' prefix


def test_infer_channel_email_rejects_malformed():
    with pytest.raises(AmbiguousAddressError):
        infer_channel("not@valid@address")
