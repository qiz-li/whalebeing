"""
Age full-resolution rows out of ais_positions_recent into the Parquet archive.

A month qualifies once it has fully elapsed AND every row in it is older than
the retention window. Qualifying months are exported to the archive, the
Parquet row count is verified against the database, and only then are the
rows deleted. Hourly rows in hourly_positions are never touched.

Intended to run monthly (cron on the stream-worker EC2). Idempotent: each run
writes a uniquely-named part file, and a month disappears from the table once
its delete succeeds.

Usage:
    python -m scripts.export_archive --archive s3://whalebeing-ais-archive/ais
"""

import argparse
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from scripts.archive import (
    batch_from_columns,
    new_column_buffers,
    open_writer,
    parquet_row_count,
    store_file,
)

FETCH_ROWS = 100_000

EXPORT_SQL = """
    SELECT v.mmsi, p.base_datetime,
           ST_X(p.position) AS lon, ST_Y(p.position) AS lat,
           p.sog, p.cog, p.heading, p.rate_of_turn, p.status
    FROM ais_positions_recent p
    JOIN vessels v ON p.vessel_id = v.id
    WHERE p.base_datetime >= %s AND p.base_datetime < %s
    ORDER BY v.mmsi, p.base_datetime
"""


def next_month(month: datetime) -> datetime:
    return (month.replace(day=28) + timedelta(days=5)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def months_to_export(conn, retain_days: int) -> list[datetime]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retain_days)
    rows = conn.execute(
        "SELECT DISTINCT date_trunc('month', base_datetime) FROM ais_positions_recent ORDER BY 1"
    ).fetchall()
    return [m for (m,) in rows if next_month(m) <= cutoff]


def export_month(conn, month: datetime, archive_uri: str, tmp_dir: Path) -> None:
    end = next_month(month)
    local = tmp_dir / f"live_{month:%Y_%m}.parquet"
    writer = open_writer(local)
    cols = new_column_buffers()
    exported = 0

    with conn.cursor(name=f"export_{month:%Y%m}") as cur:
        cur.itersize = FETCH_ROWS
        cur.execute(EXPORT_SQL, (month, end))
        for mmsi, ts, lon, lat, sog, cog, heading, rot, status in cur:
            cols["mmsi"].append(mmsi)
            cols["base_datetime"].append(ts)
            cols["lon"].append(lon)
            cols["lat"].append(lat)
            cols["sog"].append(sog)
            cols["cog"].append(cog)
            cols["heading"].append(heading)
            cols["rate_of_turn"].append(rot)
            cols["status"].append(status)
            exported += 1
            if exported % FETCH_ROWS == 0:
                writer.write_batch(batch_from_columns(cols))
                for buf in cols.values():
                    buf.clear()

    if cols["mmsi"]:
        writer.write_batch(batch_from_columns(cols))
    writer.close()

    if exported == 0:
        local.unlink(missing_ok=True)
        print(f"  {month:%Y-%m}: nothing to export")
        return

    if parquet_row_count(str(local)) != exported:
        raise RuntimeError(f"{month:%Y-%m}: Parquet row count mismatch, aborting before delete")

    rel_key = (
        f"source=live/year={month.year}/month={month.month:02d}"
        f"/part-{int(time.time())}.parquet"
    )
    dest = store_file(local, archive_uri, rel_key)

    deleted = conn.execute(
        "DELETE FROM ais_positions_recent WHERE base_datetime >= %s AND base_datetime < %s",
        (month, end),
    ).rowcount
    conn.commit()

    if deleted != exported:
        # Rows written mid-run for an already-elapsed month shouldn't happen, but
        # surface it loudly rather than silently dropping data.
        print(f"  WARNING {month:%Y-%m}: exported {exported:,} but deleted {deleted:,}")
    print(f"  {month:%Y-%m}: {exported:,} rows → {dest} (deleted {deleted:,})")


def main():
    parser = argparse.ArgumentParser(description="Archive aged rows from ais_positions_recent")
    parser.add_argument(
        "--archive",
        required=True,
        help="Archive URI: s3://bucket/prefix or a local directory",
    )
    parser.add_argument("--retain-days", type=int, default=30)
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/whalebeing"
        ),
        help="PostgreSQL connection string (defaults to $DATABASE_URL)",
    )
    args = parser.parse_args()

    conn = psycopg.connect(args.database_url)
    months = months_to_export(conn, args.retain_days)
    if not months:
        print("No months old enough to archive.")
        return

    print(f"Archiving {len(months)} month(s): {', '.join(f'{m:%Y-%m}' for m in months)}")
    with tempfile.TemporaryDirectory(prefix="ais_export_") as tmp:
        for month in months:
            export_month(conn, month, args.archive, Path(tmp))
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
