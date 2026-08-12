"""
Authentication & Authorization module.

JWT token generation / verification, bcrypt password hashing,
FastAPI dependencies for RBAC.
"""

import hashlib
import hmac
import json
import time
import base64
import os
from typing import Optional, Callable

from fastapi import Request, HTTPException, status


# ── Config ────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", "nexusai-dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))


# ── Password hashing (bcrypt direct) ──────────────

try:
    import bcrypt as _bcrypt

    def hash_password(password: str) -> str:
        """Hash a password using bcrypt with cost factor 12."""
        salt = _bcrypt.gensalt(rounds=12)
        return _bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify_password(password: str, hashed: str) -> bool:
        """Verify a password against a bcrypt hash."""
        if not hashed or not hashed.startswith("$2"):
            return False
        try:
            return _bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

except ImportError:
    # Fallback: SHA-256 with salt (less secure, but no external dep)
    import secrets

    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return f"sha256${salt}${h}"

    def verify_password(password: str, hashed: str) -> bool:
        try:
            algo, salt, h = hashed.split("$", 2)
            if algo != "sha256":
                return False
            return hmac.compare_digest(
                hashlib.sha256(f"{salt}:{password}".encode()).hexdigest(), h
            )
        except Exception:
            return False


# ── JWT (hand-rolled, no external JWT lib needed) ──

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_access_token(data: dict, expires_in: Optional[int] = None) -> str:
    """Create a JWT token. ``data`` should contain at least ``sub`` (username) and ``role``."""
    now = int(time.time())
    exp = now + (expires_in or JWT_EXPIRE_MINUTES * 60)
    payload = {**data, "iat": now, "exp": exp}
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}

    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode())

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    sig_b64 = _b64encode(signature)

    return f"{signing_input}.{sig_b64}"


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises HTTPException(401) on failure."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token format")

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"

        # Verify signature
        expected_sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        provided_sig = _b64decode(sig_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            raise ValueError("Invalid signature")

        payload = json.loads(_b64decode(payload_b64))

        # Check expiry
        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("Token expired")

        return payload

    except (ValueError, json.JSONDecodeError, Exception) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependencies ──────────────────────────

def _extract_token(request: Request) -> str:
    """Extract Bearer token from Authorization header or query param."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    # Also accept token as query param (for WebSocket)
    token = request.query_params.get("token")
    if token:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(request: Request) -> dict:
    """FastAPI dependency: extract and verify the current user from JWT."""
    token = _extract_token(request)
    payload = decode_token(token)
    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("sub"),
        "role": payload.get("role", "viewer"),
    }


def require_role(*allowed_roles: str) -> Callable:
    """
    FastAPI dependency factory: require the user to have one of ``allowed_roles``.

    Usage::

        from common.auth import require_role

        @app.delete("/api/v1/users/{id}", dependencies=[Depends(require_role("admin"))])
        async def delete_user(id: int): ...
    """
    async def _check(request: Request):
        user = await get_current_user(request)
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user['role']}' is not authorized. Required: {allowed_roles}",
            )
        return user

    return _check


# ── Public paths (no auth required) ───────────────

PUBLIC_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
})

PUBLIC_PREFIXES = (
    "/ws/",  # WebSocket (uses query param token)
)


def is_public_path(path: str) -> bool:
    """Check if a path bypasses authentication."""
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False
