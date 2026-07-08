"""
CLI tool to download and ingest NOAA MarineCadastre AIS data.

Per day:
  1. Download the daily zip (with retries).
  2. Stream-filter rows to the West Coast bounding box (bounded memory).
  3. Write the full-resolution day to the Parquet archive (S3 or local dir).
  4. Reduce to the first fix per (vessel, hour) and load vessels + hourly_positions.

Only the hourly reduction enters PostgreSQL; full resolution lives in the archive.
Daily volume is small enough (~70K hourly rows) that indexes stay in place.

Usage:
    python -m scripts.ingest_ais --start-date 2025-01-01 --end-date 2025-12-31 \
        --archive s3://whalebeing-ais-archive/ais
    python -m scripts.ingest_ais --date 2025-06-01 --archive /tmp/ais-archive
"""

import argparse
import csv
import io
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import psycopg

from scripts.archive import (
    batch_from_columns,
    new_column_buffers,
    open_writer,
    parquet_row_count,
    store_file,
)
from scripts.constants import DEFAULT_DATABASE_URL, in_bbox

NOAA_URL = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/{year}/AIS_{year}_{month:02d}_{day:02d}.zip"

PARQUET_FLUSH_ROWS = 250_000

STAGING_DDL = """
CREATE TEMP TABLE IF NOT EXISTS staging_vessels (
    mmsi BIGINT,
    imo TEXT,
    vessel_name TEXT,
    call_sign TEXT,
    vessel_type INT,
    length REAL,
    width REAL,
    draft REAL,
    cargo INT
);
CREATE TEMP TABLE IF NOT EXISTS staging_hourly (
    mmsi BIGINT,
    hour TIMESTAMP,
    lon DOUBLE PRECISION,
    lat DOUBLE PRECISION,
    sog REAL,
    cog REAL
);
"""


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


def download_day(target_date: date, dest_dir: Path, retries: int = 3) -> tuple[date, Path | None]:
    """Download a single day's zip file with retries. Returns (date, path) or (date, None) on failure."""
    url = NOAA_URL.format(year=target_date.year, month=target_date.month, day=target_date.day)
    dest = dest_dir / f"AIS_{target_date}.zip"
    for attempt in range(retries):
        try:
            with httpx.stream("GET", url, timeout=600, follow_redirects=True) as response:
                response.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=131072):
                        f.write(chunk)
            return (target_date, dest)
        except Exception as e:
            dest.unlink(missing_ok=True)
            if attempt < retries - 1:
                wait = 30 * (attempt + 1)
                print(f"  Download failed for {target_date} (attempt {attempt+1}): {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"  Download failed for {target_date} after {retries} attempts: {e}")
    return (target_date, None)


def filter_day(zip_path: Path, parquet_path: Path) -> tuple[dict, dict, int, int]:
    """Stream the day's CSV: write bbox-filtered rows to Parquet, and reduce in memory.

    Returns (vessels, hourly, kept_rows, total_rows) where
      vessels: mmsi -> latest non-empty static attributes
      hourly:  (mmsi, hour) -> (base_datetime, lon, lat, sog, cog) for the first fix
    """
    vessels: dict[int, dict] = {}
    hourly: dict[tuple[int, datetime], tuple] = {}
    total_rows = 0
    kept_rows = 0

    writer = open_writer(parquet_path)
    cols = new_column_buffers()

    def flush():
        if cols["mmsi"]:
            writer.write_batch(batch_from_columns(cols))
            for buf in cols.values():
                buf.clear()

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

                if not in_bbox(lat, lon):
                    continue

                try:
                    mmsi = int(row["MMSI"])
                    ts = datetime.fromisoformat(row["BaseDateTime"])
                except (ValueError, KeyError):
                    continue

                sog = parse_float(row.get("SOG", ""))
                cog = parse_float(row.get("COG", ""))
                heading = parse_float(row.get("Heading", ""))
                rot = parse_float(row.get("ROT", ""))
                status = parse_int(row.get("Status", ""))

                cols["mmsi"].append(mmsi)
                cols["base_datetime"].append(ts)
                cols["lon"].append(lon)
                cols["lat"].append(lat)
                cols["sog"].append(sog)
                cols["cog"].append(cog)
                cols["heading"].append(heading)
                cols["rate_of_turn"].append(rot)
                cols["status"].append(status)
                kept_rows += 1
                if kept_rows % PARQUET_FLUSH_ROWS == 0:
                    flush()

                hour = ts.replace(minute=0, second=0, microsecond=0)
                existing = hourly.get((mmsi, hour))
                if existing is None or ts < existing[0]:
                    hourly[(mmsi, hour)] = (ts, lon, lat, sog, cog)

                if mmsi not in vessels:
                    raw_imo = row.get("IMO") or ""
                    vessels[mmsi] = {
                        "imo": None if (not raw_imo or raw_imo == "IMO0000000") else raw_imo,
                        "vessel_name": row.get("VesselName") or None,
                        "call_sign": row.get("CallSign") or None,
                        "vessel_type": parse_int(row.get("VesselType", "")),
                        "length": parse_float(row.get("Length", "")),
                        "width": parse_float(row.get("Width", "")),
                        "draft": parse_float(row.get("Draft", "")),
                        "cargo": parse_int(row.get("Cargo", "")),
                    }

    flush()
    writer.close()
    return vessels, hourly, kept_rows, total_rows


def load_day(conn, vessels: dict, hourly: dict):
    """Load one day's vessels and hourly reduction into PostgreSQL."""
    with conn.transaction():
        cur = conn.cursor()
        cur.execute(STAGING_DDL)
        cur.execute("TRUNCATE staging_vessels, staging_hourly")

        # write_row adapts and escapes each value, so text fields containing
        # tabs/newlines/backslashes (vessel names, call signs) can't corrupt the stream.
        with cur.copy(
            "COPY staging_vessels (mmsi, imo, vessel_name, call_sign, vessel_type,"
            " length, width, draft, cargo) FROM STDIN"
        ) as copy:
            for mmsi, v in vessels.items():
                copy.write_row((
                    mmsi, v["imo"], v["vessel_name"], v["call_sign"],
                    v["vessel_type"], v["length"], v["width"], v["draft"], v["cargo"],
                ))

        with cur.copy("COPY staging_hourly (mmsi, hour, lon, lat, sog, cog) FROM STDIN") as copy:
            for (mmsi, hour), (_, lon, lat, sog, cog) in hourly.items():
                copy.write_row((mmsi, hour, lon, lat, sog, cog))

        cur.execute("""
            INSERT INTO vessels (mmsi, imo, vessel_name, call_sign, vessel_type, length, width, draft, cargo)
            SELECT mmsi, imo, vessel_name, call_sign, vessel_type, length, width, draft, cargo
            FROM staging_vessels
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
            INSERT INTO hourly_positions (vessel_id, hour, position, sog, cog)
            SELECT v.id, s.hour, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), s.sog, s.cog
            FROM staging_hourly s
            JOIN vessels v ON v.mmsi = s.mmsi
            ON CONFLICT (vessel_id, hour) DO NOTHING
        """)


def ingest_day(conn, target_date: date, zip_path: Path, archive_uri: str, tmp_dir: Path, verbose: bool = True):
    t0 = time.time()

    parquet_tmp = tmp_dir / f"noaa_{target_date}.parquet"
    vessels, hourly, kept_rows, total_rows = filter_day(zip_path, parquet_tmp)

    if kept_rows == 0:
        parquet_tmp.unlink(missing_ok=True)
        if verbose:
            print(f"  {target_date}: no rows in bbox")
        return

    if parquet_row_count(str(parquet_tmp)) != kept_rows:
        raise RuntimeError(f"{target_date}: Parquet row count mismatch")

    rel_key = (
        f"source=noaa/year={target_date.year}"
        f"/month={target_date.month:02d}/day={target_date.day:02d}.parquet"
    )
    dest = store_file(parquet_tmp, archive_uri, rel_key)
    archive_time = time.time() - t0

    t1 = time.time()
    load_day(conn, vessels, hourly)
    load_time = time.time() - t1

    if verbose:
        print(f"  {target_date}: {kept_rows:,}/{total_rows:,} rows → {dest} "
              f"({len(hourly):,} hourly) — archive:{archive_time:.1f}s load:{load_time:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Ingest NOAA AIS data")
    parser.add_argument("--date", type=str, help="Single date to ingest (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=str, help="Start of date range (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End of date range (YYYY-MM-DD)")
    parser.add_argument(
        "--archive",
        required=True,
        help="Archive URI for full-resolution Parquet: s3://bucket/prefix or a local directory",
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
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
            ingest_day(conn, d, path, args.archive, tmp_dir)
            path.unlink(missing_ok=True)
        except Exception as e:
            print(f"  {d}: ERROR — {e}")
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

    conn.close()
    total_time = time.time() - t_start
    print(f"\nDone! {days_done} days in {total_time/60:.1f} minutes ({total_time/3600:.1f} hours)")

    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
