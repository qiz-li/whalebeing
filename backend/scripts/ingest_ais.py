"""
CLI tool to download and ingest NOAA MarineCadastre AIS data into PostgreSQL.

Uses COPY + staging table with indexes dropped for maximum throughput.
Downloads are parallelized to keep the network saturated.

Usage:
    python -m scripts.ingest_ais --start-date 2023-06-01 --end-date 2023-06-07
    python -m scripts.ingest_ais --date 2023-06-01
"""

import argparse
import csv
import io
import sys
import tempfile
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
import psycopg

# West Coast bounding box: Baja approaches → Vancouver/BC
BBOX = {
    "lat_min": 30.0,
    "lat_max": 51.0,
    "lon_min": -130.0,
    "lon_max": -115.0,
}

NOAA_URL = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/{year}/AIS_{year}_{month:02d}_{day:02d}.zip"

STAGING_DDL = """
CREATE TEMP TABLE IF NOT EXISTS staging_ais (
    mmsi BIGINT,
    base_datetime TEXT,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    sog REAL,
    cog REAL,
    heading REAL,
    rot REAL,
    status INT,
    transceiver_class TEXT,
    imo TEXT,
    vessel_name TEXT,
    call_sign TEXT,
    vessel_type INT,
    length REAL,
    width REAL,
    draft REAL,
    cargo INT
);
"""

INDEXES_TO_DROP = [
    "idx_positions_geom",
    "idx_positions_vessel_time",
    "idx_positions_datetime",
]

INDEXES_TO_CREATE = [
    "CREATE INDEX idx_positions_geom ON ais_positions USING GIST (position)",
    "CREATE INDEX idx_positions_vessel_time ON ais_positions (vessel_id, base_datetime)",
    "CREATE INDEX idx_positions_datetime ON ais_positions (base_datetime)",
]


def parse_float(val: str) -> float | None:
    try:
        v = float(val)
        return v if v == v else None
    except (ValueError, TypeError):
        return None


def parse_int(val: str) -> int | None:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def tsv_val(val) -> str:
    """Format a value for PostgreSQL COPY text format. None becomes \\N."""
    if val is None:
        return "\\N"
    return str(val)


def download_day(target_date: date, dest_dir: Path) -> tuple[date, Path | None]:
    """Download a single day's zip file. Returns (date, path) or (date, None) on failure."""
    url = NOAA_URL.format(year=target_date.year, month=target_date.month, day=target_date.day)
    dest = dest_dir / f"AIS_{target_date}.zip"
    try:
        with httpx.stream("GET", url, timeout=600, follow_redirects=True) as response:
            response.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=131072):
                    f.write(chunk)
        return (target_date, dest)
    except Exception as e:
        print(f"  Download failed for {target_date}: {e}")
        return (target_date, None)


def filter_to_tsv(zip_path: Path) -> tuple[io.BytesIO, int, int]:
    """Read zip, filter to bbox, return TSV bytes buffer + row counts."""
    buf = io.BytesIO()
    total_rows = 0
    kept_rows = 0

    with zipfile.ZipFile(zip_path) as zf:
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as csv_file:
            reader = csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8"))

            for row in reader:
                total_rows += 1
                lat = parse_float(row.get("LAT", ""))
                lon = parse_float(row.get("LON", ""))

                if lat is None or lon is None:
                    continue

                if not (
                    BBOX["lat_min"] <= lat <= BBOX["lat_max"]
                    and BBOX["lon_min"] <= lon <= BBOX["lon_max"]
                ):
                    continue

                raw_imo = row.get("IMO") or ""
                imo = None if (not raw_imo or raw_imo == "IMO0000000") else raw_imo

                line = "\t".join([
                    str(int(row["MMSI"])),
                    row["BaseDateTime"],
                    str(lat),
                    str(lon),
                    tsv_val(parse_float(row.get("SOG", ""))),
                    tsv_val(parse_float(row.get("COG", ""))),
                    tsv_val(parse_float(row.get("Heading", ""))),
                    tsv_val(parse_float(row.get("ROT", ""))),
                    tsv_val(parse_int(row.get("Status", ""))),
                    row.get("TransceiverClass") or "\\N",
                    tsv_val(imo),
                    row.get("VesselName") or "\\N",
                    row.get("CallSign") or "\\N",
                    tsv_val(parse_int(row.get("VesselType", ""))),
                    tsv_val(parse_float(row.get("Length", ""))),
                    tsv_val(parse_float(row.get("Width", ""))),
                    tsv_val(parse_float(row.get("Draft", ""))),
                    tsv_val(parse_int(row.get("Cargo", ""))),
                ]) + "\n"
                buf.write(line.encode())
                kept_rows += 1

    buf.seek(0)
    return buf, kept_rows, total_rows


def load_day(conn, target_date: date, zip_path: Path, verbose: bool = True):
    """Filter and COPY a single day's data into the database."""
    t0 = time.time()

    tsv_buf, kept_rows, total_rows = filter_to_tsv(zip_path)
    filter_time = time.time() - t0

    if kept_rows == 0:
        if verbose:
            print(f"  {target_date}: no rows in bbox")
        return

    t1 = time.time()
    with conn.transaction():
        cur = conn.cursor()
        cur.execute(STAGING_DDL)
        cur.execute("TRUNCATE staging_ais")

        with cur.copy("COPY staging_ais FROM STDIN (FORMAT text)") as copy:
            copy.write(tsv_buf.getvalue())

        cur.execute("""
            INSERT INTO vessels (mmsi, imo, vessel_name, call_sign, vessel_type, length, width, draft, cargo)
            SELECT DISTINCT ON (mmsi)
                mmsi, imo, vessel_name, call_sign, vessel_type, length, width, draft, cargo
            FROM staging_ais
            ON CONFLICT (mmsi) DO UPDATE SET
                imo = COALESCE(EXCLUDED.imo, vessels.imo),
                vessel_name = COALESCE(EXCLUDED.vessel_name, vessels.vessel_name),
                call_sign = COALESCE(EXCLUDED.call_sign, vessels.call_sign),
                vessel_type = COALESCE(EXCLUDED.vessel_type, vessels.vessel_type),
                length = COALESCE(EXCLUDED.length, vessels.length),
                width = COALESCE(EXCLUDED.width, vessels.width),
                draft = COALESCE(EXCLUDED.draft, vessels.draft)
        """)

        cur.execute("""
            INSERT INTO ais_positions (vessel_id, base_datetime, position, sog, cog, heading, rate_of_turn, status, transceiver_class)
            SELECT
                v.id,
                s.base_datetime::timestamp,
                ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326),
                s.sog, s.cog, s.heading, s.rot, s.status, s.transceiver_class
            FROM staging_ais s
            JOIN vessels v ON v.mmsi = s.mmsi
            ON CONFLICT (vessel_id, base_datetime) DO NOTHING
        """)

    load_time = time.time() - t1
    total_time = time.time() - t0

    if verbose:
        print(f"  {target_date}: {kept_rows:,}/{total_rows:,} rows — "
              f"filter:{filter_time:.1f}s load:{load_time:.1f}s total:{total_time:.1f}s")


def drop_indexes(conn):
    """Drop indexes on ais_positions for faster bulk insert."""
    cur = conn.cursor()
    for idx in INDEXES_TO_DROP:
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.commit()
    print("Dropped indexes on ais_positions")


def create_indexes(conn):
    """Recreate indexes on ais_positions after bulk load."""
    cur = conn.cursor()
    for ddl in INDEXES_TO_CREATE:
        print(f"  Creating: {ddl.split(' ON ')[0]}...")
        t0 = time.time()
        cur.execute(ddl)
        conn.commit()
        print(f"    Done in {time.time() - t0:.1f}s")
    print("All indexes rebuilt")


def main():
    parser = argparse.ArgumentParser(description="Ingest NOAA AIS data into PostgreSQL")
    parser.add_argument("--date", type=str, help="Single date to ingest (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=str, help="Start of date range (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End of date range (YYYY-MM-DD)")
    parser.add_argument("--no-reindex", action="store_true", help="Skip dropping/recreating indexes")
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@localhost:5432/whalebeing",
        help="PostgreSQL connection string",
    )
    args = parser.parse_args()

    if args.date:
        dates = [date.fromisoformat(args.date)]
    elif args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
    else:
        parser.error("Provide --date or both --start-date and --end-date")
        return

    conn = psycopg.connect(args.database_url)

    # Drop indexes for bulk load speed
    if not args.no_reindex and len(dates) > 1:
        drop_indexes(conn)

    tmp_dir = Path(tempfile.mkdtemp(prefix="ais_ingest_"))
    print(f"Ingesting {len(dates)} days...")
    sys.stdout.flush()

    t_start = time.time()
    days_done = 0

    for d in dates:
        try:
            _, path = download_day(d, tmp_dir)
            if path is None:
                print(f"  {d}: skipped (download failed)")
                days_done += 1
                continue
            load_day(conn, d, path)
            path.unlink(missing_ok=True)
        except Exception as e:
            print(f"  {d}: ERROR — {e}")
            import traceback
            traceback.print_exc()

        days_done += 1
        sys.stdout.flush()

        if days_done % 10 == 0:
            elapsed = time.time() - t_start
            rate = elapsed / days_done
            remaining = rate * (len(dates) - days_done)
            print(f"--- Progress: {days_done}/{len(dates)} days, "
                  f"{elapsed/60:.1f}min elapsed, ~{remaining/60:.1f}min remaining ---")
            sys.stdout.flush()

    # Rebuild indexes
    if not args.no_reindex and len(dates) > 1:
        print("Rebuilding indexes...")
        create_indexes(conn)

    conn.close()
    total_time = time.time() - t_start
    print(f"\nDone! {days_done} days in {total_time/60:.1f} minutes ({total_time/3600:.1f} hours)")

    # Cleanup temp dir
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
