"""
CLI tool to download and ingest NOAA MarineCadastre AIS data into PostgreSQL.

Usage:
    python -m scripts.ingest_ais --start-date 2023-06-01 --end-date 2023-06-07
    python -m scripts.ingest_ais --date 2023-06-01
"""

import argparse
import csv
import io
import tempfile
import zipfile
from datetime import date, timedelta

import httpx
import psycopg

# California coast bounding box (generous to capture offshore shipping lanes)
CA_BBOX = {
    "lat_min": 30.0,
    "lat_max": 42.0,
    "lon_min": -130.0,
    "lon_max": -115.0,
}

NOAA_URL = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/{year}/AIS_{year}_{month:02d}_{day:02d}.zip"

BATCH_SIZE = 10_000


def parse_float(val: str) -> float | None:
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (ValueError, TypeError):
        return None


def parse_int(val: str) -> int | None:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def insert_batch(conn, rows: list[dict]):
    """Upsert vessels then insert positions."""
    with conn.cursor() as cur:
        # Deduplicate vessels by MMSI within this batch
        vessels_seen = {}
        for r in rows:
            mmsi = int(r["MMSI"])
            if mmsi not in vessels_seen:
                vessels_seen[mmsi] = r

        # Upsert vessels
        vessel_values = [
            (
                int(v["MMSI"]),
                v.get("IMO") or None,
                v.get("VesselName") or None,
                v.get("CallSign") or None,
                parse_int(v.get("VesselType", "")),
                parse_float(v.get("Length", "")),
                parse_float(v.get("Width", "")),
                parse_float(v.get("Draft", "")),
                parse_int(v.get("Cargo", "")),
            )
            for v in vessels_seen.values()
        ]

        cur.executemany(
            """
            INSERT INTO vessels (mmsi, imo, vessel_name, call_sign, vessel_type, length, width, draft, cargo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (mmsi) DO UPDATE SET
                imo = COALESCE(EXCLUDED.imo, vessels.imo),
                vessel_name = COALESCE(EXCLUDED.vessel_name, vessels.vessel_name),
                call_sign = COALESCE(EXCLUDED.call_sign, vessels.call_sign),
                vessel_type = COALESCE(EXCLUDED.vessel_type, vessels.vessel_type),
                length = COALESCE(EXCLUDED.length, vessels.length),
                width = COALESCE(EXCLUDED.width, vessels.width),
                draft = COALESCE(EXCLUDED.draft, vessels.draft)
            """,
            vessel_values,
        )

        # Insert positions
        position_values = [
            (
                int(r["MMSI"]),
                r["BaseDateTime"],
                float(r["LON"]),
                float(r["LAT"]),
                parse_float(r.get("SOG", "")),
                parse_float(r.get("COG", "")),
                parse_float(r.get("Heading", "")),
                parse_int(r.get("Status", "")),
                r.get("TransceiverClass") or None,
            )
            for r in rows
        ]

        cur.executemany(
            """
            INSERT INTO ais_positions (vessel_id, base_datetime, position, sog, cog, heading, status, transceiver_class)
            SELECT v.id, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s
            FROM vessels v WHERE v.mmsi = %s
            ON CONFLICT (vessel_id, base_datetime) DO NOTHING
            """,
            [
                (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[0])
                for r in position_values
            ],
        )

    conn.commit()


def process_date(target_date: date, conn, verbose: bool = True):
    """Download and ingest AIS data for a single date."""
    url = NOAA_URL.format(year=target_date.year, month=target_date.month, day=target_date.day)

    if verbose:
        print(f"Downloading {url}...")

    with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
        with httpx.stream("GET", url, timeout=600, follow_redirects=True) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(chunk_size=65536):
                tmp.write(chunk)

        tmp.seek(0)

        if verbose:
            print(f"Processing {target_date}...")

        with zipfile.ZipFile(tmp) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as csv_file:
                reader = csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8"))
                batch = []
                total_rows = 0
                kept_rows = 0

                for row in reader:
                    total_rows += 1
                    lat = parse_float(row.get("LAT", ""))
                    lon = parse_float(row.get("LON", ""))

                    if lat is None or lon is None:
                        continue

                    # Filter to California bounding box
                    if not (
                        CA_BBOX["lat_min"] <= lat <= CA_BBOX["lat_max"]
                        and CA_BBOX["lon_min"] <= lon <= CA_BBOX["lon_max"]
                    ):
                        continue

                    batch.append(row)
                    kept_rows += 1

                    if len(batch) >= BATCH_SIZE:
                        insert_batch(conn, batch)
                        batch = []
                        if verbose:
                            print(f"  ... {kept_rows:,} California rows inserted so far")

                if batch:
                    insert_batch(conn, batch)

    if verbose:
        print(f"Done: {target_date} — {kept_rows:,} / {total_rows:,} rows kept (California filter)")


def main():
    parser = argparse.ArgumentParser(description="Ingest NOAA AIS data into PostgreSQL")
    parser.add_argument("--date", type=str, help="Single date to ingest (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=str, help="Start of date range (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End of date range (YYYY-MM-DD)")
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

    with psycopg.connect(args.database_url) as conn:
        for d in dates:
            try:
                process_date(d, conn)
            except httpx.HTTPStatusError as e:
                print(f"Failed to download {d}: {e}")
            except Exception as e:
                print(f"Error processing {d}: {e}")


if __name__ == "__main__":
    main()
