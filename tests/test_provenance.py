"""Provenance / DID tests."""

from __future__ import annotations

import base64
import sqlite3

from stolperstein.provenance import (
    ENV_KEY,
    derive_did_from_pubkey,
    generate_did_key,
    get_or_create_install_did,
    load_signing_key,
    public_key_from_private,
    write_signing_key_file,
)


def test_did_is_deterministic_from_keypair():
    """Same private key → same DID, always."""
    priv, pub, did = generate_did_key()
    # Round-trip via raw bytes and recompute
    pub2 = public_key_from_private(priv)
    did2 = derive_did_from_pubkey(pub2)
    assert did == did2


def test_did_format():
    """Ed25519 did:key identifiers start with did:key:z6Mk..."""
    _, _, did = generate_did_key()
    assert did.startswith("did:key:z6Mk")


def test_env_var_overrides_file(tmp_path, monkeypatch):
    """If MCP_STOLPERSTEIN_SIGNING_KEY is set, the file is ignored."""
    key_path = tmp_path / "ignored.key"
    key_path.write_bytes(b"\xff" * 32)
    monkeypatch.setenv(ENV_KEY, base64.b64encode(b"\x00" * 32).decode())

    loaded = load_signing_key(str(key_path))
    assert loaded == b"\x00" * 32  # env, not file


def test_signing_key_file_is_mode_0o600(tmp_path):
    """write_signing_key_file enforces chmod 0o600."""
    key_path = tmp_path / "stolperstein.key"
    write_signing_key_file(str(key_path), b"\x01" * 32)
    assert key_path.exists()
    mode = key_path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_get_or_create_install_did_is_single_install(tmp_path, monkeypatch):
    """Second call returns the same DID; install_identity has exactly one row."""
    monkeypatch.setenv(ENV_KEY, base64.b64encode(b"\x00" * 32).decode())
    db_path = str(tmp_path / "install.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE install_identity ("
        "did TEXT PRIMARY KEY, public_key BLOB NOT NULL, created_at TEXT NOT NULL)"
    )

    did1 = get_or_create_install_did(conn, key_path=str(tmp_path / "s.key"))
    did2 = get_or_create_install_did(conn, key_path=str(tmp_path / "s.key"))
    assert did1 == did2
    count = conn.execute("SELECT COUNT(*) FROM install_identity").fetchone()[0]
    assert count == 1
