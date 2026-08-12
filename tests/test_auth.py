"""Unit tests for JWT authentication and password hashing."""
import time
import pytest

from common.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    is_public_path,
)
from fastapi import HTTPException


class TestPasswordHashing:
    """Password hash and verify tests."""

    def test_hash_and_verify(self):
        password = "secure_password_123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True

    def test_empty_hash(self):
        assert verify_password("anything", "") is False

    def test_invalid_hash_format(self):
        assert verify_password("password", "not-a-hash") is False


class TestJWT:
    """JWT token creation and verification tests."""

    def test_create_and_decode(self):
        payload = {"sub": "admin", "user_id": 1, "role": "admin"}
        token = create_access_token(payload)
        assert isinstance(token, str)
        assert token.count(".") == 2  # header.payload.signature

        decoded = decode_token(token)
        assert decoded["sub"] == "admin"
        assert decoded["user_id"] == 1
        assert decoded["role"] == "admin"
        assert "iat" in decoded
        assert "exp" in decoded

    def test_expired_token(self):
        payload = {"sub": "admin", "role": "admin"}
        # Create token that's already expired
        token = create_access_token(payload, expires_in=-1)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401

    def test_invalid_signature(self):
        payload = {"sub": "admin", "role": "admin"}
        token = create_access_token(payload)
        # Tamper with the token
        parts = token.split(".")
        tampered = f"{parts[0]}.{parts[1]}.invalid_signature"
        with pytest.raises(HTTPException) as exc_info:
            decode_token(tampered)
        assert exc_info.value.status_code == 401

    def test_malformed_token(self):
        with pytest.raises(HTTPException):
            decode_token("not.a.valid.token.at.all")
        with pytest.raises(HTTPException):
            decode_token("onlytwoparts.second")

    def test_custom_expiry(self):
        payload = {"sub": "user", "role": "viewer"}
        token = create_access_token(payload, expires_in=3600)
        decoded = decode_token(token)
        assert decoded["exp"] - decoded["iat"] == 3600


class TestPublicPaths:
    """Test public path detection."""

    def test_public_paths(self):
        assert is_public_path("/health") is True
        assert is_public_path("/api/v1/auth/login") is True
        assert is_public_path("/metrics") is True
        assert is_public_path("/docs") is True

    def test_protected_paths(self):
        assert is_public_path("/api/v1/devices") is False
        assert is_public_path("/api/v1/alerts") is False
        assert is_public_path("/api/v1/ai/diagnosis/CNC-A01") is False

    def test_websocket_paths(self):
        assert is_public_path("/ws/sensors") is True
        assert is_public_path("/ws/alerts") is True
