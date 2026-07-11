"""Per-install identity for provenance stamping.

Design decisions (see openspec/changes/cq-v1-alignment-and-hooks/design.md §6):

- One Ed25519 keypair per install.
- Identifier is `did:key:z<multibase>` following the did:key spec.
- **Private key is NEVER stored in the SQLite DB** — it lives either at
  `/data/stolperstein.key` (mode 0o600, unchanged filename — see the
  product rename's design.md: renaming on-disk paths risks losing the
  signing key across a redeploy) or in the `MCP_STOLPERFALLE_SIGNING_KEY`
  env var (base64-encoded).
- DB holds only the public key and the derived DID string.

This module is stdlib-plus-cryptography; no MCP or FastMCP coupling, so it
can be used by both the server and the migration runner.
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

logger = logging.getLogger(__name__)

ENV_KEY = "MCP_STOLPERFALLE_SIGNING_KEY"


def default_key_path() -> str:
    """Default signing-key path — alongside the configured DB (not in /data
    hardcoded) so it works in dev, tests, and production identically.
    """
    from stolperfalle.config import settings
    import os.path
    db_dir = os.path.dirname(os.path.abspath(settings.cq_local_db_path))
    return os.path.join(db_dir, "stolperstein.key")


# Kept as a constant for tests / docs; runtime callers should use default_key_path().
# Filename intentionally NOT renamed with the product (stolperstein.key, not
# stolperfalle.key) — this is the actual on-disk filename in the production
# volume; renaming it would make the server generate a fresh keypair on next
# boot instead of finding the existing one, rotating the install DID.
DEFAULT_KEY_PATH = "/data/stolperstein.key"

# did:key multicodec prefix for Ed25519 public keys: 0xed 0x01
_ED25519_MULTICODEC = b"\xed\x01"

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out: list[str] = []
    while n > 0:
        n, rem = divmod(n, 58)
        out.append(_BASE58_ALPHABET[rem])
    # leading zero bytes → leading '1'
    leading = len(data) - len(data.lstrip(b"\x00"))
    return ("1" * leading) + "".join(reversed(out))


def derive_did_from_pubkey(pub_bytes: bytes) -> str:
    """Compute the `did:key:z...` identifier for an Ed25519 public key.

    Spec reference: https://w3c-ccg.github.io/did-method-key/#ed25519-x25519
    """
    if len(pub_bytes) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(pub_bytes)}")
    payload = _ED25519_MULTICODEC + pub_bytes
    return "did:key:z" + _b58encode(payload)


def generate_did_key() -> tuple[bytes, bytes, str]:
    """Generate a fresh Ed25519 keypair + DID.

    Returns: (private_key_bytes_32, public_key_bytes_32, did_string).
    """
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    did = derive_did_from_pubkey(pub_bytes)
    return priv_bytes, pub_bytes, did


def write_signing_key_file(path: str, priv_bytes: bytes) -> None:
    """Write the private key to a file with mode 0o600."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write with restrictive umask so file starts 0o600.
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, priv_bytes)
    finally:
        os.close(fd)
    # Belt-and-braces: enforce mode even if umask interfered.
    os.chmod(str(p), 0o600)


def load_signing_key(path: str | None = None) -> bytes | None:
    """Load the private key, preferring the env var over the file.

    Returns raw 32-byte Ed25519 private key, or None if neither source has it.
    """
    env_val = os.environ.get(ENV_KEY, "").strip()
    if env_val:
        try:
            key = base64.b64decode(env_val, validate=True)
            if len(key) != 32:
                raise ValueError(f"key must be 32 bytes, got {len(key)}")
            return key
        except Exception:
            logger.warning("Failed to decode %s; falling back to key file", ENV_KEY)
    if path is None:
        path = default_key_path()
    try:
        with open(path, "rb") as f:
            key = f.read()
            if len(key) != 32:
                raise ValueError(f"signing key at {path} is {len(key)} bytes, want 32")
            return key
    except FileNotFoundError:
        return None


def public_key_from_private(priv_bytes: bytes) -> bytes:
    """Derive the public key from a raw Ed25519 private key."""
    priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def public_key_to_pem(pub_bytes: bytes) -> bytes:
    """Serialize a public key to PEM for storage in the DB."""
    pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def get_or_create_install_did(
    conn: sqlite3.Connection,
    key_path: str | None = None,
) -> str:
    """Return the install's DID, creating a keypair + install_identity row
    on first call. Called by migration m0003 and (defensively) by the store
    on every boot.
    """
    row = conn.execute(
        "SELECT did FROM install_identity LIMIT 1"
    ).fetchone()
    if row is not None:
        return row["did"] if isinstance(row, sqlite3.Row) else row[0]

    if key_path is None:
        key_path = default_key_path()

    # If env var set, derive identity from it; else generate fresh + persist.
    env_priv = load_signing_key(key_path)
    if env_priv is None:
        priv_bytes, pub_bytes, did = generate_did_key()
        write_signing_key_file(key_path, priv_bytes)
    else:
        priv_bytes = env_priv
        pub_bytes = public_key_from_private(priv_bytes)
        did = derive_did_from_pubkey(pub_bytes)

    pub_pem = public_key_to_pem(pub_bytes)
    conn.execute(
        "INSERT INTO install_identity (did, public_key, created_at) VALUES (?, ?, ?)",
        [did, pub_pem, datetime.now(timezone.utc).isoformat()],
    )
    return did
