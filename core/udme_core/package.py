"""Canonical serialisation, checksum and signing (plan 5.4)."""
from __future__ import annotations
import base64, hashlib, json, time, secrets
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from .model import Package

MAX_PACKAGE_BYTES = 50 * 1024 * 1024


def canonical_json(pkg: Package) -> bytes:
    d = pkg.model_dump(mode="json")
    d["source"].pop("scan_timestamp", None)  # stable hash across repeated scans
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def schema_hash(pkg: Package) -> str:
    return hashlib.sha256(canonical_json(pkg)).hexdigest()


def generate_keypair() -> tuple[str, str]:
    """Ed25519 keypair as base64 (private, public). The private key never leaves the agent."""
    k = Ed25519PrivateKey.generate()
    return (base64.b64encode(k.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode(),
            base64.b64encode(k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())


def valid_public_key(b64: str) -> bool:
    try: Ed25519PublicKey.from_public_bytes(base64.b64decode(b64, validate=True)); return True
    except Exception: return False


def sign_envelope(pkg: Package, *, tenant_id: str, agent_id: str, scan_id: str, private_key: str) -> dict:
    body = pkg.model_dump_json()
    env = {"tenant_id": tenant_id, "agent_id": agent_id, "scan_id": scan_id,
           "package_version": pkg.package_version, "created_at": int(time.time()),
           "nonce": secrets.token_hex(16), "checksum": hashlib.sha256(body.encode()).hexdigest(), "package": body}
    env["signature"] = base64.b64encode(Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key)).sign(_msg(env))).decode()
    return env


def _msg(env: dict) -> bytes:
    return "|".join(str(env[k]) for k in ("tenant_id", "agent_id", "scan_id", "created_at", "nonce", "checksum")).encode()


def verify_envelope(env: dict, public_key: str, max_age_s: int = 900) -> Package:
    """Raises ValueError with a safe PACKAGE_INVALID reason."""
    if len(env.get("package", "")) > MAX_PACKAGE_BYTES: raise ValueError("oversized")
    if abs(time.time() - int(env["created_at"])) > max_age_s: raise ValueError("stale_timestamp")
    if hashlib.sha256(env["package"].encode()).hexdigest() != env["checksum"]: raise ValueError("bad_checksum")
    try: Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(base64.b64decode(env["signature"]), _msg(env))
    except (InvalidSignature, ValueError, KeyError): raise ValueError("bad_signature")
    pkg = Package.model_validate_json(env["package"])
    if pkg.package_version != "1.0": raise ValueError("unsupported_package_version")
    return pkg
