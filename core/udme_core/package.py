"""Canonical serialisation, checksum and signing (plan 5.4)."""
from __future__ import annotations
import hashlib, hmac, json, time, secrets
from .model import Package

MAX_PACKAGE_BYTES = 50 * 1024 * 1024


def canonical_json(pkg: Package) -> bytes:
    d = pkg.model_dump(mode="json")
    d["source"].pop("scan_timestamp", None)  # stable hash across repeated scans
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def schema_hash(pkg: Package) -> str:
    return hashlib.sha256(canonical_json(pkg)).hexdigest()


def sign_envelope(pkg: Package, *, tenant_id: str, agent_id: str, scan_id: str, secret: str) -> dict:
    body = pkg.model_dump_json()
    env = {"tenant_id": tenant_id, "agent_id": agent_id, "scan_id": scan_id,
           "package_version": pkg.package_version, "created_at": int(time.time()),
           "nonce": secrets.token_hex(16), "checksum": hashlib.sha256(body.encode()).hexdigest(), "package": body}
    env["signature"] = hmac.new(secret.encode(), _msg(env), hashlib.sha256).hexdigest()
    return env


def _msg(env: dict) -> bytes:
    return "|".join(str(env[k]) for k in ("tenant_id", "agent_id", "scan_id", "created_at", "nonce", "checksum")).encode()


def verify_envelope(env: dict, secret: str, max_age_s: int = 900) -> Package:
    """Raises ValueError with a safe PACKAGE_INVALID reason."""
    if len(env.get("package", "")) > MAX_PACKAGE_BYTES: raise ValueError("oversized")
    if abs(time.time() - int(env["created_at"])) > max_age_s: raise ValueError("stale_timestamp")
    if hashlib.sha256(env["package"].encode()).hexdigest() != env["checksum"]: raise ValueError("bad_checksum")
    good = hmac.new(secret.encode(), _msg(env), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, env["signature"]): raise ValueError("bad_signature")
    pkg = Package.model_validate_json(env["package"])
    if pkg.package_version != "1.0": raise ValueError("unsupported_package_version")
    return pkg
