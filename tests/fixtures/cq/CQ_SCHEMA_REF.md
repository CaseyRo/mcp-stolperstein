# Vendored CQ schema reference

The `knowledge_unit.json` file in this directory is a vendored copy of Mozilla AI's CQ protocol schema, pinned at a known commit for reproducible round-trip conformance testing.

- **Upstream repo:** https://github.com/mozilla-ai/cq
- **Path in repo:** `schema/knowledge_unit.json`
- **Pinned commit:** `92b35de20ffc6500a5a50be16750530ca160a816`
- **Pinned at:** 2026-04-17
- **Upstream raw URL at this pin:** https://raw.githubusercontent.com/mozilla-ai/cq/92b35de20ffc6500a5a50be16750530ca160a816/schema/knowledge_unit.json
- **Upstream discussion of extensions we propose:** https://github.com/mozilla-ai/cq/discussions/286

## How to update

Run `make sync-cq-schema` (see project `Makefile`). That target:

1. Fetches the current `main` commit SHA from `mozilla-ai/cq`.
2. Downloads the current `schema/knowledge_unit.json`.
3. Updates the pinned SHA in this file to the new one.
4. Runs `uv run pytest tests/test_cq_schema.py` to confirm our serializers still pass strict validation against the new pin. If not, triage the diff: strict serializer must continue to validate.

Never edit the vendored `knowledge_unit.json` by hand — it is a byte-for-byte copy of upstream.
