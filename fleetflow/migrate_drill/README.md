# Old→new migration drill (16.0.1.1.0 → 16.0.1.2.0)

A genuine prior-version → new-version upgrade on a **disposable** database. A fresh
install of the new code plus an update of the *same* version does not exercise an
old-data migration; this drill installs the reviewed baseline, populates
representative records with the old code, then upgrades to the new module and
asserts both preservation and the new effective-cutover semantics. It never
touches the normal development database (isolated compose project + volumes,
`down -v` teardown).

## What it proves

Seeded under the **old** module (`seed_migration.py`): a standalone verified
credential (with a source file), a precise superseded renewal chain, a
revoked/rejected credential (with a source file), a future-effective renewal left
as a draft, and an *ambiguous legacy* chain whose successor has an imprecise
effective date (only creatable under the old code, which had no precise-date
guard).

Asserted under the **new** module (`assert_migration.py`):
- the `ir_attachment.ff_source_lock` column exists and the migration initialised it;
- ids, supersession links, verification/revocation attribution and source-byte
  hashes are unchanged;
- the legacy superseded predecessor's authority now ends at its successor's
  cutover (no fall-back past it), while pre-cutover and successor-window coverage
  are correct;
- the ambiguous legacy chain grants no coverage (surfaced for review, not guessed);
- untouched records (standalone verified, draft renewal) still behave.

## Run it

From a checkout of the new code (paths below use POSIX shell; on Windows Git Bash
prefix docker commands with `MSYS_NO_PATHCONV=1` and use `C:/...`-style paths):

```sh
NEW=$(pwd)                                  # the new checkout (this tree)
OLD=$(mktemp -d)/ff-old                     # baseline tree
BASELINE=e60aba4c                           # last reviewed baseline (16.0.1.1.0)

# 1) Materialise the baseline module + deployment glue, then overlay the new
#    deployment glue (entrypoint drill hook + these scripts) onto it. The glue is
#    deployment-only; the MODULE under old test stays at the baseline version.
mkdir -p "$OLD"
git archive "$BASELINE" custom_addons fleetflow | tar -x -C "$OLD"
cp "$NEW/fleetflow/entrypoint.py" "$OLD/fleetflow/entrypoint.py"
mkdir -p "$OLD/fleetflow/migrate_drill"
cp "$NEW/fleetflow/migrate_drill/"*.py "$OLD/fleetflow/migrate_drill/"
touch "$OLD/odoo-bin"; cp "$NEW/fleetflow/.env" "$OLD/fleetflow/.env"

CF="$NEW/fleetflow/migrate_drill/compose.drill.yaml"
ENVF="$NEW/fleetflow/.env"
dc(){ docker compose --env-file "$ENVF" -f "$CF" -p fleetflow-migrate "$@"; }

# 2) Disposable db, install the OLD (1.1.0) module, seed old data.
FF_WS="$OLD" dc up -d --wait db
FF_WS="$OLD" dc run --rm web -i fleetflow_operations --without-demo=all --stop-after-init --no-http
FF_WS="$OLD" dc run --rm -e FF_DRILL=/workspace/fleetflow/migrate_drill/seed_migration.py web drill

# 3) Upgrade to the NEW (1.2.0) module (runs the migration), then assert.
FF_WS="$NEW" dc run --rm web -u fleetflow_operations --without-demo=all --stop-after-init --no-http
FF_WS="$NEW" dc run --rm -e FF_DRILL=/workspace/fleetflow/migrate_drill/assert_migration.py web drill

FF_WS="$NEW" dc down -v
```

Expected: `SEED_OK …` after step 2, `module fleetflow_operations: Running migration
[16.0.1.2.0>] post-migrate` during the upgrade, and `ASSERT_OK …` after step 3.
