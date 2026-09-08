"""ThaiD OAuth2/OpenID Connect integration powered by Authlib.

The implementation follows the endpoint names shown in the supplied ThaiD
training material: OpenID discovery, authorization, token, introspection and
revoke endpoints. Secrets are read exclusively from environment variables.
"""
from __future__ import annotations

import hashlib
from typing import Any

import requests
from authlib.integrations.flask_client import OAuth
from flask import current_app, session


oauth = OAuth()


def init_thaid(app) -> None:
    """Register the ThaiD OAuth client with the Flask application."""
    oauth.init_app(app)
    if not app.config.get("THAID_ENABLED"):
        return

    register_options: dict[str, Any] = {
        "client_id": app.config.get("THAID_CLIENT_ID"),
        "client_secret": app.config.get("THAID_CLIENT_SECRET"),
        "client_kwargs": {
            "scope": app.config.get("THAID_SCOPE", "pid openid name_en name"),
            "token_endpoint_auth_method": app.config.get(
                "THAID_TOKEN_ENDPOINT_AUTH_METHOD", "client_secret_basic"
            ),
        },
    }

    discovery = app.config.get("THAID_DISCOVERY_URL")
    if discovery:
        register_options["server_metadata_url"] = discovery
    else:
        register_options.update(
            {
                "authorize_url": app.config.get("THAID_AUTHORIZATION_ENDPOINT"),
                "access_token_url": app.config.get("THAID_TOKEN_ENDPOINT"),
            }
        )

    oauth.register("thaid", **register_options)


def is_configured() -> bool:
    cfg = current_app.config
    endpoint_ok = bool(cfg.get("THAID_DISCOVERY_URL")) or bool(
        cfg.get("THAID_AUTHORIZATION_ENDPOINT") and cfg.get("THAID_TOKEN_ENDPOINT")
    )
    return bool(
        cfg.get("THAID_ENABLED")
        and cfg.get("THAID_CLIENT_ID")
        and cfg.get("THAID_CLIENT_SECRET")
        and endpoint_ok
    )


def _api_headers() -> dict[str, str]:
    api_key = current_app.config.get("THAID_API_KEY")
    if not api_key:
        return {}
    header_name = current_app.config.get("THAID_API_KEY_HEADER", "x-api-key")
    return {header_name: api_key}


def authorize_redirect(redirect_uri: str):
    """Start OAuth2 Authorization Code flow with state and OIDC nonce."""
    if not is_configured():
        raise RuntimeError("ThaiD configuration is incomplete")
    return oauth.thaid.authorize_redirect(redirect_uri)


def exchange_code_and_get_profile() -> tuple[dict[str, Any], dict[str, Any]]:
    """Exchange callback code and return token plus normalized claim source.

    Authlib validates the OIDC ID token when discovery metadata is available.
    When the token response does not contain userinfo claims, the function
    falls back to the configured userinfo endpoint and then introspection.
    """
    token = oauth.thaid.authorize_access_token(headers=_api_headers() or None)

    profile = token.get("userinfo")
    if profile:
        return token, dict(profile)

    userinfo_endpoint = current_app.config.get("THAID_USERINFO_ENDPOINT")
    if userinfo_endpoint:
        response = oauth.thaid.get(
            userinfo_endpoint,
            token=token,
            headers=_api_headers() or None,
        )
        response.raise_for_status()
        return token, response.json()

    introspected = introspect_token(token.get("access_token", ""))
    if introspected:
        return token, introspected

    # Last fallback: claims returned directly in the token response.
    return token, token


def introspect_token(access_token: str) -> dict[str, Any]:
    endpoint = current_app.config.get("THAID_INTROSPECT_URL")
    if not endpoint or not access_token:
        return {}

    response = requests.post(
        endpoint,
        headers={**_api_headers(), "Accept": "application/json"},
        data={"token": access_token, "token_type_hint": "access_token"},
        auth=(
            current_app.config.get("THAID_CLIENT_ID"),
            current_app.config.get("THAID_CLIENT_SECRET"),
        ),
        timeout=30,
        verify=current_app.config.get("THAID_VERIFY_SSL", True),
    )
    response.raise_for_status()
    data = response.json()
    return data if data.get("active", True) else {}


def revoke_token(access_token: str) -> bool:
    endpoint = current_app.config.get("THAID_REVOKE_URL")
    if not endpoint or not access_token:
        return False
    response = requests.post(
        endpoint,
        headers={**_api_headers(), "Accept": "application/json"},
        data={"token": access_token, "token_type_hint": "access_token"},
        auth=(
            current_app.config.get("THAID_CLIENT_ID"),
            current_app.config.get("THAID_CLIENT_SECRET"),
        ),
        timeout=30,
        verify=current_app.config.get("THAID_VERIFY_SSL", True),
    )
    return response.ok


def remember_token(token: dict[str, Any]) -> None:
    """Store only the short-lived access token in the signed server session."""
    session["thaid_access_token"] = token.get("access_token")


def normalize_profile(profile: dict[str, Any]) -> dict[str, str]:
    subject = str(
        profile.get("sub")
        or profile.get("pid")
        or profile.get("uuid")
        or profile.get("user_id")
        or ""
    ).strip()
    if not subject:
        raise ValueError("ThaiD did not return a stable subject or pid claim")

    full_name = str(profile.get("name") or profile.get("name_en") or "").strip()
    if not full_name:
        given = str(profile.get("given_name") or profile.get("given_name_en") or "").strip()
        middle = str(profile.get("middle_name") or profile.get("middle_name_en") or "").strip()
        family = str(profile.get("family_name") or profile.get("family_name_en") or "").strip()
        full_name = " ".join(v for v in (given, middle, family) if v).strip()
    if not full_name:
        full_name = "ThaiD User"

    email = str(profile.get("email") or "").strip().lower()
    if not email:
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:20]
        email = f"thaid-{digest}@local.invalid"

    reference_hash = hashlib.sha256(subject.encode("utf-8")).hexdigest()
    return {
        "subject": subject,
        "full_name": full_name,
        "email": email,
        "reference_hash": reference_hash,
    }
