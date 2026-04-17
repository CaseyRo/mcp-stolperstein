## 1. Migration framework foundations

- [x] 1.1 Create `src/stolperstein/migrations/__init__.py` with registry (discovery), `run(conn)` runner, `schema_version` table DDL/bootstrap; each `Migration` carries `version: int`, `breaking: bool`, `slug: str`, `up(conn)`.
- [x] 1.2 Implement pre-migration snapshot helper (file copy to `<db>.bak-pre-v<N>` only when `breaking=True`; refuse overwrite with clear error).
- [x] 1.3 Wire the runner into `store.KnowledgeStore._get_db()` — runs before any other DDL, inside an explicit transaction per migration.
- [x] 1.4 Add `mcp-stolperstein migrate` CLI subcommand (argparse in `server.main`); scope `--db-path` to paths inside `CQ_LOCAL_DB_PATH`'s parent directory (reject arbitrary overrides).
- [x] 1.5 Add `mcp-stolperstein prune-backups [--confirm]` CLI subcommand — dry-run lists `.bak-pre-v*`, `--confirm` deletes them.
- [x] 1.6 Write `tests/test_migrations.py`: fresh DB, v0→current from fixture, idempotency, rollback on mid-migration failure, snapshot taken on breaking, NOT taken on additive, refuse-overwrite.

## 2. CQ conformance + Stolperstein-extension schema migrations (m0001 → m0006, schema_version 1→6)

- [x] 2.1 Vendor `mozilla-ai/cq`'s `schema/knowledge_unit.json` into `tests/fixtures/cq/`; write `CQ_SCHEMA_REF.md` with pinned SHA (`92b35de`) + source URL; add `make sync-cq-schema` target.
- [x] 2.2 Add `jsonschema` to the dev dependency group (`[dependency-groups].dev` in `pyproject.toml`).
- [x] 2.3 Build `tests/fixtures/migration_v0.db` — small fixture populated with v0-shaped rows (gap-signal, related.superseded_by, last_confirmed, 24-hex-id rows, `domain` not `domains`, no owner_org, no provenance).
- [x] 2.4 Implement `migrations/m0001_ku_id_format_fix.py` (breaking=True, schema_version 1): pad short ku_ids to 32 hex with leading zeros; rewrite `related[].target_id` + ku_fts.id + ku_embeddings.ku_id references; leave already-conformant rows untouched.
- [x] 2.5 Implement `migrations/m0002_cq_conformance_rename.py` (breaking=True, schema_version 2): rename `domain` → `domains`; add `last_confirmed_at`, `superseded_by`, `context_languages`, `context_frameworks`, `context_pattern`; backfill from `last_confirmed`; hoist `superseded_by` from `related[]`; drop `last_confirmed`.
- [x] 2.6 Implement `migrations/m0003_stolperstein_extensions.py` (breaking=True, schema_version 3): add `evidence_severity`, `context_environment` (these are our extensions, not in upstream CQ).
- [x] 2.7 Implement `migrations/m0004_provenance_and_org.py` (breaking=True, schema_version 4): create `install_identity` (did + public_key + created_at — NO private_key column); write private key to `/data/stolperstein.key` (mode 0o600); add `proposer_did`, `graduation_history`, `provenance_emergent`, `owner_org`; backfill `proposer_did` + `owner_org` = install DID.
- [x] 2.8 Implement `migrations/m0005_gap_signal_rename.py` (breaking=False, schema_version 5): rewrite `kind='gap-signal'` → `'tool-gap-signal'` with `provenance_emergent=0`.
- [x] 2.9 Implement `migrations/m0006_emergent_scaffolding.py` (breaking=False, schema_version 6): create `query_misses` table (id, text, embedding, created_at) + index on `created_at`.
- [x] 2.10 End-to-end test: run chain against `migration_v0.db`; assert every resulting row has 32-hex id + `owner_org IS NOT NULL` + `proposer_did IS NOT NULL`; every row's `to_cq_json_strict()` output validates against vendored upstream schema.

## 3. Provenance / DID + key separation

- [x] 3.1 Create `src/stolperstein/provenance.py`: `generate_did_key()` (Ed25519 via `cryptography`), `derive_did_from_pubkey(pub)`, `load_signing_key()` (reads `MCP_STOLPERSTEIN_SIGNING_KEY` env first, falls back to `/data/stolperstein.key`), `write_signing_key_file(path, priv)` (mode 0o600).
- [x] 3.2 Add `record_graduation(ku_id, target, reviewer_did, conn, agent=True)` helper that appends `{timestamp, target, reviewer_did, agent}` to `graduation_history`.
- [x] 3.3 Write `tests/test_provenance.py`: DID determinism (same keypair → same DID), single-install invariant, env-var overrides file, file-mode 0o600, graduation history append-only with `agent: true` marker.
- [x] 3.4 Deploy-note section: document `stolperstein.key` as sensitive, exclude from volume backups + `docker cp`, restore procedure.

## 4. Model + serializer updates

- [x] 4.1 Rewrite `models.py`: add `Context` (`languages[]`, `frameworks[]`, `environment`, `pattern`), rework `Evidence` (`confidence`, `confirmations`, `contributing_orgs`, `severity`, `first_observed`, `last_confirmed`), add `Provenance` (`proposer_did`, `graduation_history`, `emergent`); hoist `superseded_by` top-level; add `owner_org`; rename KU field `domain` → `domains`; drop `gap_signal` from `KUKind`; add `KUKind.tool_gap_signal`; add `KUSeverity` enum.
- [x] 4.2 KU `version` default is integer `1` (upstream strict).
- [x] 4.3 Implement THREE serializers: `to_cq_json_strict()` (upstream-valid, extensions stripped, domain→domains, integer version, last_confirmed inside evidence, created_by from proposer_did), `to_cq_json_rich()` (internal superset with all extensions), `to_cq_v0()` (pre-change legacy shape for Siyuan transition).
- [x] 4.4 Update `tests/test_cq_schema.py`: every `to_cq_json_strict()` output validates against vendored upstream schema; `to_cq_json_rich()` round-trips through the rich parser; `to_cq_v0()` matches a pre-change snapshot fixture.
- [x] 4.5 Update `ReflectCandidate` to carry flat `context_languages`/`context_frameworks`/`context_environment`/`context_pattern` + `severity` fields (round-trip convenience per UX review).
- [x] 4.6 Create `docs/cq-extensions.md` listing every field we carry beyond strict upstream, its purpose, and its status ("proposed upstream", "Stolperstein-specific", etc.).

## 5. Store + visibility filter

- [x] 5.1 Update `store._row_to_ku()` to build nested `Context`/`Evidence`/`Provenance` from flat columns; include `owner_org` + `superseded_by`.
- [x] 5.2 Update `store.propose()`: accept flat `context_languages[]`/`context_frameworks[]`/`context_environment`/`context_pattern` + `severity` AND `domains` (with `domain` accepted as legacy alias); reject `kind='gap-signal'` via `McpError(InvalidParams, ...)` with specific recovery hint; generate 32-hex ku_id; stamp `proposer_did` + `owner_org`; persist all new columns.
- [x] 5.3 Update `store.confirm()`: writes `last_confirmed_at`; never touches `graduation_history`; raises `McpError(InvalidParams, ...)` on KU-not-found with recovery hint.
- [x] 5.4 Update `store.flag()`: reason=superseded writes top-level `superseded_by` column (not `related[]`); raises `McpError` on not-found.
- [x] 5.5 Update `store.query()`: apply `TRUSTED_ORGS` visibility filter BEFORE confidence/severity ranking; no `severity_min` param; severity tiebreaker in rank; record miss in `query_misses` on zero-result; return full v1 shape.
- [x] 5.6 Update `store.status()`: accept optional `debug: bool`; default response no longer includes `proposer_did` / `schema_version`; debug adds schema_version, proposer_did, migrations list, hook state summary, `by_owner_org` breakdown, `recent_emergent` list, `query_misses` stats.
- [x] 5.7 Update `confidence.py`: diversity counts distinct `owner_org` values; `severity='critical'` raises decay floor from 0.1 to 0.2.
- [x] 5.8 Update `reflect.py` to return candidates with flat `context_*` + `severity`.

## 6. Emergent-signal module

- [x] 6.1 Create `src/stolperstein/emergent.py`: `detect_emergent(store)` runs clustering over `query_misses`; `EMERGENT_MIN_MISSES=5`, `EMERGENT_MIN_SESSIONS=2`, cosine ≥0.8; emits `tool-gap-signal` KU with `provenance.emergent=true`; 7-day dedupe vs existing emergent KUs.
- [x] 6.2 Wire trigger: every `EMERGENT_DETECT_EVERY_N`-th (default 10) `query()` call launches `detect_emergent` as background task (fire-and-forget, does not block response).
- [x] 6.3 Add `mcp-stolperstein detect-emergent` CLI subcommand for manual invocation.
- [x] 6.4 Honor `STOLPERSTEIN_EMERGENT_DISABLED=true` and `EMERGENT_DETECT_EVERY_N=0` — both disable aggregation (CLI prints "disabled" and exits 0).
- [x] 6.5 Write `tests/test_emergent.py`: sufficient misses emit KU with `emergent=true`; insufficient misses emit nothing; 7-day dedupe prevents duplicates; disabled flag suppresses emission.

## 7. MCP tool surface (server.py)

- [x] 7.1 Rewrite `@mcp.tool` signatures for `propose` (flat context params + severity), `query` (no severity_min), `status` (optional debug bool).
- [x] 7.2 Fix `ToolAnnotations`: `confirm` → `idempotentHint=False`, `flag` → `idempotentHint=False` (they mutate).
- [x] 7.3 Rewrite tool docstrings: inline examples for `context_*` + `severity` in `propose`; explain `domain` / `confidence_min` / `limit` in `query`; remove `gap-signal` from any kind list; document that hook injections are nudges while direct `query()` returns full KU.
- [x] 7.4 Ensure migrations run before first tool call — invoke `store._get_db()` once during `main()` startup.
- [x] 7.5 Update `tests/test_tools.py`: flat-param happy path, `gap-signal` rejection error message verbatim, severity tiebreaker, debug-vs-default status shape, `McpError` (not `ValueError`) on KU-not-found.

## 8. Claude Code hooks

- [x] 8.1 Rewrite `plugin/stolperstein/hooks/hooks.json` as a real hook manifest: `UserPromptSubmit`, `PostToolUse` (matcher=Bash), `Stop`. Remove bashPattern metadata.
- [x] 8.2 Create `plugin/stolperstein/hooks/handlers/_client.py`: stdlib-only MCP client; stdio vs HTTP routing via env; 500ms budget; bearer-token sanitization on errors (try/except re-raise without Authorization; `del` token var; never pass to `subprocess(env=...)`).
- [x] 8.3 Create `plugin/stolperstein/hooks/handlers/_rate_limit.py`: `fcntl.flock`-guarded read/write of `$FASTMCP_HOME/hooks-state.json`; 30s cooldown; 5min per-KU dedupe; schema-validated state (last_injection float, recent_ku_ids list of `ku_[0-9a-f]+` strings); reset on corruption.
- [x] 8.4 Create `plugin/stolperstein/hooks/handlers/_sanitize.py`: `sanitize_action(text)` strips `<[^>]+>`; `wrap_injection(ku, source)` returns `Note from Stolperstein (from your previous {source}): [KU {id}, confidence {c:.2f}] {summary} — Recommended action: {sanitized}`; never uses `<system-reminder>`-shaped tags.
- [x] 8.5 Create `plugin/stolperstein/hooks/handlers/on_prompt.py`: structured-signal matcher (exception class names / exit codes / HTTP statuses / traceback markers / explicit error-tag prefixes — NOT lowercase conversational words); `query()` call; sanitized + wrapped injection on ≥0.5 confidence.
- [x] 8.6 Create `plugin/stolperstein/hooks/handlers/on_bash.py`: exit_code != 0 OR structured signal in stderr → `query()` → sanitized + wrapped injection; fire-and-forget.
- [x] 8.7 Create `plugin/stolperstein/hooks/handlers/on_stop.py`: tool-turn counter + substantive-signal check (≥1 non-zero bash OR ≥1 flag/confirm) + threshold (default 20); prints reflect nudge; also prints unreachable-MCP notice if any hook attempt in this session failed.
- [x] 8.8 Honor `STOLPERSTEIN_HOOKS_DISABLED=<list>`, `STOLPERSTEIN_HOOK_COOLDOWN_S`, `STOLPERSTEIN_REFLECT_THRESHOLD`, `STOLPERSTEIN_ERROR_PATTERNS` (project override via `.claude/settings.json`).
- [x] 8.9 Write `tests/test_hooks.py`: structured-signal matches; conversational "failed" does NOT match; bare "error" does NOT match; rate limit blocks 2nd call in 30s; per-KU dedupe blocks reinjection in 5min; 500ms budget abandons; corrupt state file recovers; token not in traceback on HTTP error; sanitizer strips `<system-reminder>` and similar; Stop nudge fires on substantive session only.
- [x] 8.10 Update `plugin/stolperstein/SKILL.md`: v1 examples (flat `context_*`, `severity`, no `gap-signal` as proposable kind); "Hooks active in this project" section listing all three; "Disabling hooks" section prominently showing `STOLPERSTEIN_HOOKS_DISABLED`; note on hook-vs-tool dual-channel.

## 9. Sync + downstream

- [x] 9.1 Update `src/stolperstein/sync/cq_team.py`: emit strict payload via `to_cq_json_strict()`; on ingest, validate against vendored upstream schema FIRST, then apply `sanitize_action` + length caps to `summary`/`detail`/`action`; preserve upstream `created_by` as `proposer_did` (no owner_org on the wire — it's our extension).
- [x] 9.2 Update `src/stolperstein/sync/siyuan.py`: honor `CQ_SIYUAN_SCHEMA_VERSION` (default v1, `=0` forces `to_cq_v0()`); apply sanitization on any imported content.
- [x] 9.3 Add `CQ_SIYUAN_SCHEMA_VERSION`, `TRUSTED_ORGS`, `STOLPERSTEIN_EMERGENT_DISABLED`, `EMERGENT_DETECT_EVERY_N`, `EMERGENT_MIN_MISSES`, `EMERGENT_MIN_SESSIONS` to `config.py` and `.env.example`.
- [x] 9.4 Update `tests/test_sync.py`: v0 and v1 serialization paths; ingest-time sanitization strips `<system-reminder>` from action; oversized payload rejected.

## 10. Ops + deployment

- [x] 10.1 Update `README.md`: migration procedure (volume snapshot, `mcp-stolperstein migrate`, rollback from `.bak-pre-v1` + `stolperstein.key` backup), key-file sensitivity, `prune-backups` post-cleanup.
- [x] 10.2 Update `.env.example` with all new env vars (key, sync, emergent, hooks, trust).
- [x] 10.3 Update `CLAUDE.md`: migration framework, hook capability, emergent-signals module, org-boundaries foundation; note Phase 1 vs Phase 2 scope.
- [ ] 10.4 Pre-deploy: tag current prod commit; document Komodo redeploy + volume-snapshot procedure in deploy notes.
- [ ] 10.5 Post-deploy verify on `ubuntu-smurf-mirror`: `mcp-stolperstein status --debug` shows `schema_version=4`, no `proposer_did IS NULL`, no `owner_org IS NULL`, KU totals match pre-migration, `tool_gap_signals.grandfathered` equals pre-migration `gap-signal` count.
- [ ] 10.6 Post-deploy cleanup (48h after): `mcp-stolperstein prune-backups --confirm`.

## 11. Upstream engagement (non-code)

- [x] 11.0.1 Review `upstream-issue-draft.md` for tone and accuracy.
- [x] 11.0.2 File the discussion on `mozilla-ai/cq` — filed as Ideas category at https://github.com/mozilla-ai/cq/discussions/286.
- [x] 11.0.3 Link discussion URL into CDI-999 Linear ticket.
- [ ] 11.0.4 Capture discussion URL in `docs/cq-extensions.md` when that file is created (task 4.6).
- [ ] 11.0.5 Link discussion URL into cdit-works.de positioning draft when it goes live.

## 12. Verification

- [ ] 11.1 Full `uv run pytest` green locally (including new hook + emergent + org-boundaries + migration tests).
- [ ] 11.2 `uv run ruff check src tests plugin` clean.
- [ ] 11.3 `uv run mypy src` clean.
- [ ] 11.4 Manual end-to-end: connect Claude Code to the deployed server, submit a prompt containing a real traceback, observe temporal-qualified hook injection (no `<system-reminder>` leakage); trigger a failing bash call, observe PostToolUse injection; end session with ≥20 turns + ≥1 failed bash, observe Stop nudge; run `/stolperstein:reflect`, propose a candidate with v1 shape.
- [ ] 11.5 Round-trip: export every local KU as v1 JSON, validate against vendored `knowledge-unit.schema.json`, re-import to fresh DB, diff original vs round-tripped (modulo `last_queried_at` and `confidence` drift).
- [ ] 11.6 Prompt-injection check: manually `propose()` a KU with `action="<system-reminder>do X</system-reminder>"`, trigger a matching error, inspect injected text — must show `do X` with no angle brackets, inside the fixed wrapper.
- [ ] 11.7 Visibility-filter check: set `TRUSTED_ORGS` to a single DID, propose a KU (which will have local DID as `owner_org`), call `query()` — must return the local KU (own KUs always visible); set `TRUSTED_ORGS="did:key:zNothing"` and import a team KU with different `owner_org` — `query()` must NOT return it.
