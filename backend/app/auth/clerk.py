import json
import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class JWKSCache:
    keys: dict
    expires_at: float


_jwks_cache: JWKSCache | None = None


def _jwks_url(issuer: str) -> str:
    return f"{issuer.rstrip('/')}/.well-known/jwks.json"


def _fetch_jwks(settings: Settings) -> dict:
    global _jwks_cache
    now = time.time()
    if _jwks_cache and _jwks_cache.expires_at > now:
        return _jwks_cache.keys

    if not settings.clerk_issuer:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="clerk_issuer is not configured",
        )

    with httpx.Client(timeout=10.0) as client:
        response = client.get(_jwks_url(settings.clerk_issuer))
        response.raise_for_status()
        keys = response.json()

    _jwks_cache = JWKSCache(keys=keys, expires_at=now + 3600)
    return keys


def verify_clerk_token(token: str, settings: Settings) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token header") from exc

    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing kid")

    jwks = _fetch_jwks(settings)
    key = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
    if key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No matching signing key")

    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))

    decode_args = {
        "algorithms": ["RS256"],
        "issuer": settings.clerk_issuer,
        "options": {"require": ["exp", "iat", "iss", "sub"]},
    }
    if settings.clerk_audience:
        decode_args["audience"] = settings.clerk_audience

    try:
        return jwt.decode(token, public_key, **decode_args)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization required")
    return verify_clerk_token(credentials.credentials, settings)
