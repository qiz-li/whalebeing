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
from datetime import datetime, timezone

import psycopg
import websockets.sync.client as ws_client

from scripts.constants import AISSTREAM_BBOX, DEFAULT_DATABASE_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
HEADING_UNAVAILABLE = 511  # AIS sentinel for "no heading data"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
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
        return datetime.now(timezone.utc).replace(tzinfo=None)


def upsert_vessel(cur, mmsi: int, name: str | None) -> int:
    """Upsert the vessel and return its id (resolved once, reused for all inserts)."""
    cur.execute(
        """
        INSERT INTO vessels (mmsi, vessel_name)
        VALUES (%s, %s)
        ON CONFLICT (mmsi) DO UPDATE SET
            vessel_name = COALESCE(EXCLUDED.vessel_name, vessels.vessel_name)
        RETURNING id
        """,
        (mmsi, name),
    )
    return cur.fetchone()[0]


def insert_position(
    cur, vessel_id: int, lat: float, lon: float,
    sog: float | None, cog: float | None,
    heading: float | None, rate_of_turn: float | None,
    status: int | None, timestamp: datetime,
):
    cur.execute(
        """
        INSERT INTO ais_positions_recent (vessel_id, base_datetime, position, sog, cog, heading, rate_of_turn, status)
        VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s)
        ON CONFLICT (vessel_id, base_datetime) DO NOTHING
        """,
        (vessel_id, timestamp, lon, lat, sog, cog, heading, rate_of_turn, status),
    )

    cur.execute(
        """
        INSERT INTO hourly_positions (vessel_id, hour, position, sog, cog)
        VALUES (%s, date_trunc('hour', %s::timestamp), ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s)
        ON CONFLICT (vessel_id, hour) DO NOTHING
        """,
        (vessel_id, timestamp, lon, lat, sog, cog),
    )

    cur.execute(
        """
        INSERT INTO latest_positions (vessel_id, base_datetime, position, sog, cog, heading)
        VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)
        ON CONFLICT (vessel_id) DO UPDATE SET
            base_datetime = EXCLUDED.base_datetime,
            position = EXCLUDED.position,
            sog = EXCLUDED.sog,
            cog = EXCLUDED.cog,
            heading = EXCLUDED.heading
        WHERE EXCLUDED.base_datetime > latest_positions.base_datetime
        """,
        (vessel_id, timestamp, lon, lat, sog, cog, heading),
    )


def run():
    if not API_KEY:
        logger.error("AISSTREAM_API_KEY not set")
        return

    subscribe_msg = json.dumps({
        "APIKey": API_KEY,
        "BoundingBoxes": AISSTREAM_BBOX,
        "FilterMessageTypes": ["PositionReport"],
    })

    conn = None
    processed = 0

    while True:
        try:
            if conn is None or conn.closed:
                conn = psycopg.connect(DATABASE_URL, autocommit=True)
                logger.info("Connected to database")

            with ws_client.connect(AISSTREAM_URL, close_timeout=10, ping_interval=None) as websocket:
                websocket.send(subscribe_msg)
                logger.info("AISstream connected — streaming West Coast")

                for raw in websocket:
                    fields = parse_message(raw)
                    if fields is None:
                        continue
                    try:
                        with conn.transaction():
                            with conn.cursor() as cur:
                                vessel_id = upsert_vessel(cur, fields["mmsi"], fields["name"])
                                insert_position(
                                    cur, vessel_id, fields["lat"], fields["lon"],
                                    fields["sog"], fields["cog"], fields["heading"],
                                    fields["rate_of_turn"], fields["status"], fields["timestamp"],
                                )
                    except psycopg.Error as e:
                        # A dead/broken DB connection must not silently drop every
                        # message: reconnect (via the outer loop) instead of swallowing.
                        logger.warning(f"DB write failed: {e} — reconnecting")
                        conn.close()
                        conn = None
                        raise

                    processed += 1
                    if processed % 1000 == 0:
                        logger.info(f"Processed {processed} positions")

        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down")
            break
        except Exception as e:
            logger.warning(f"Stream/DB interrupted: {e} — reconnecting in 5s")
            time.sleep(5)

    if conn is not None:
        conn.close()


def parse_message(raw) -> dict | None:
    """Parse one AISstream frame into insert fields, or None to skip it."""
    try:
        msg = json.loads(raw)
        position = msg.get("Message", {}).get("PositionReport", {})
        if not position:
            return None
        meta = msg.get("MetaData", {})
        mmsi = int(meta.get("MMSI", 0))
        if mmsi == 0:
            return None
        lat = position.get("Latitude")
        lon = position.get("Longitude")
        if lat is None or lon is None:
            return None

        heading_raw = position.get("TrueHeading")
        heading = float(heading_raw) if heading_raw not in (None, HEADING_UNAVAILABLE) else None
        rot_raw = position.get("RateOfTurn")

        return {
            "mmsi": mmsi,
            "lat": lat,
            "lon": lon,
            "sog": position.get("Sog"),
            "cog": position.get("Cog"),
            "heading": heading,
            "rate_of_turn": float(rot_raw) if rot_raw is not None else None,
            "status": position.get("NavigationalStatus"),
            "name": meta.get("ShipName", "").strip() or None,
            "timestamp": parse_timestamp(meta.get("time_utc", "")),
        }
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        logger.debug(f"Skipping malformed message: {e}")
        return None


if __name__ == "__main__":
    run()
