"""
Standalone AISstream WebSocket consumer for deployment on EC2.

Connects to AISstream, filters to the West Coast bounding box,
and writes vessel positions to PostgreSQL via psycopg (sync).

Each position message updates three tables in one transaction:
  - ais_positions_recent: rolling full-resolution window (pruned by export_archive.py)
  - hourly_positions: first fix per vessel per hour (ON CONFLICT DO NOTHING)
  - latest_positions: one row per vessel, kept at the newest fix

Usage:
    python -m scripts.stream_worker

Environment variables:
    DATABASE_URL - PostgreSQL connection string
    AISSTREAM_API_KEY - AISstream API key
"""

import json
import logging
import os
import time
from datetime import datetime

import psycopg
import websockets.sync.client as ws_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
WEST_COAST_BBOX = [[[30, -130], [51, -115]]]

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/whalebeing"
)
API_KEY = os.environ.get("AISSTREAM_API_KEY", "")


def parse_timestamp(time_str: str) -> datetime:
    try:
        clean = time_str.split("+")[0].strip()
        if "." in clean:
            date_part, frac = clean.split(".")
            frac = frac[:6]
            clean = f"{date_part}.{frac}"
        return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S.%f")
    except (ValueError, AttributeError, IndexError):
        return datetime.utcnow()


def upsert_vessel(cur, mmsi: int, name: str | None):
    cur.execute(
        """
        INSERT INTO vessels (mmsi, vessel_name)
        VALUES (%s, %s)
        ON CONFLICT (mmsi) DO UPDATE SET
            vessel_name = COALESCE(EXCLUDED.vessel_name, vessels.vessel_name)
        """,
        (mmsi, name),
    )


def insert_position(
    cur, mmsi: int, lat: float, lon: float,
    sog: float | None, cog: float | None,
    heading: float | None, rate_of_turn: float | None,
    status: int | None, timestamp: datetime,
):
    cur.execute(
        """
        INSERT INTO ais_positions_recent (vessel_id, base_datetime, position, sog, cog, heading, rate_of_turn, status)
        SELECT v.id, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s
        FROM vessels v WHERE v.mmsi = %s
        ON CONFLICT (vessel_id, base_datetime) DO NOTHING
        """,
        (timestamp, lon, lat, sog, cog, heading, rate_of_turn, status, mmsi),
    )

    cur.execute(
        """
        INSERT INTO hourly_positions (vessel_id, hour, position, sog, cog)
        SELECT v.id, date_trunc('hour', %s::timestamp), ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s
        FROM vessels v WHERE v.mmsi = %s
        ON CONFLICT (vessel_id, hour) DO NOTHING
        """,
        (timestamp, lon, lat, sog, cog, mmsi),
    )

    cur.execute(
        """
        INSERT INTO latest_positions (vessel_id, base_datetime, position, sog, cog, heading)
        SELECT v.id, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s
        FROM vessels v WHERE v.mmsi = %s
        ON CONFLICT (vessel_id) DO UPDATE SET
            base_datetime = EXCLUDED.base_datetime,
            position = EXCLUDED.position,
            sog = EXCLUDED.sog,
            cog = EXCLUDED.cog,
            heading = EXCLUDED.heading
        WHERE EXCLUDED.base_datetime > latest_positions.base_datetime
        """,
        (timestamp, lon, lat, sog, cog, heading, mmsi),
    )


def run():
    if not API_KEY:
        logger.error("AISSTREAM_API_KEY not set")
        return

    subscribe_msg = json.dumps({
        "APIKey": API_KEY,
        "BoundingBoxes": WEST_COAST_BBOX,
        "FilterMessageTypes": ["PositionReport"],
    })

    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    logger.info("Connected to database")

    batch_count = 0

    while True:
        try:
            with ws_client.connect(AISSTREAM_URL, close_timeout=10, ping_interval=None) as websocket:
                websocket.send(subscribe_msg)
                logger.info("AISstream connected — streaming West Coast")

                for raw in websocket:
                    try:
                        msg = json.loads(raw)
                        meta = msg.get("MetaData", {})
                        position = msg.get("Message", {}).get("PositionReport", {})

                        if not position:
                            continue

                        mmsi = int(meta.get("MMSI", 0))
                        if mmsi == 0:
                            continue

                        lat = position.get("Latitude")
                        lon = position.get("Longitude")
                        if lat is None or lon is None:
                            continue

                        sog = position.get("Sog")
                        cog = position.get("Cog")
                        heading_raw = position.get("TrueHeading")
                        heading = float(heading_raw) if heading_raw is not None and heading_raw != 511 else None
                        rot_raw = position.get("RateOfTurn")
                        rate_of_turn = float(rot_raw) if rot_raw is not None else None
                        status = position.get("NavigationalStatus")
                        name = meta.get("ShipName", "").strip() or None

                        timestamp = parse_timestamp(meta.get("time_utc", ""))

                        with conn.transaction():
                            with conn.cursor() as cur:
                                upsert_vessel(cur, mmsi, name)
                                insert_position(cur, mmsi, lat, lon, sog, cog, heading, rate_of_turn, status, timestamp)

                        batch_count += 1
                        if batch_count % 1000 == 0:
                            logger.info(f"Processed {batch_count} positions")

                    except Exception as e:
                        logger.debug(f"Skipping message: {e}")

        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down")
            break
        except BaseException as e:
            logger.warning(f"AISstream disconnected: {e} — reconnecting in 5s")
            time.sleep(5)
    conn.close()


if __name__ == "__main__":
    run()
