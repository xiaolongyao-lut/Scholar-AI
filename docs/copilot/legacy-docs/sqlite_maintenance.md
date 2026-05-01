# SQLite Maintenance

This repository now treats SQLite as the primary durable store for the writing runtime and resource layers.

## Managed databases

- `WRITING_RUNTIME_DB_PATH` → defaults to `output/writing_runtime_state.sqlite3`
- `WRITING_RESOURCE_DB_PATH` → defaults to `output/writing_resources_state.sqlite3`

If either environment variable is unset, the code falls back to the repo-local `output/` directory.

## Health and repair

Use the maintenance helper to inspect and repair the managed databases:

```powershell
python sqlite_maintenance.py health --target both
python sqlite_maintenance.py checkpoint --target both --mode PASSIVE
python sqlite_maintenance.py vacuum --target both
```

## Backup and restore

The backup command creates a manifest named `sqlite_maintenance_manifest.json` alongside copied database files.

```powershell
python sqlite_maintenance.py backup --destination _backups/sqlite-latest --target both
python sqlite_maintenance.py restore --source _backups/sqlite-latest --target both
```

## Baseline scripts

- `create_baseline_snapshot.py` now wraps the maintenance backup flow for the managed SQLite databases.
- `restore_from_baseline.py` now restores those managed databases before copying the legacy metadata files.

## Operational guidance

- Prefer a local SSD for the database files; avoid network shares for day-to-day writes.
- Run `checkpoint` before a large backup and `vacuum` after major churn or before a long-lived snapshot.
- The runtime and resource stores will skip SQLite loading if the database fails health checks, which keeps the JSON snapshot fallback usable.