import asyncio
import json
import logging
from datetime import datetime

import websockets

from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

WEST_COAST_BBOX = [[[30, -130], [51, -115]]]

_task: asyncio.Task | None = None


async def _upsert_vessel(conn, mmsi: int, name: str | None, ship_type: int | None, imo: str | None):
    await conn.execute(
        """
        INSERT INTO vessels (mmsi, vessel_name, vessel_type, imo)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (mmsi) DO UPDATE SET
            vessel_name = COALESCE(EXCLUDED.vessel_name, vessels.vessel_name),
            vessel_type = COALESCE(EXCLUDED.vessel_type, vessels.vessel_type),
            imo = COALESCE(EXCLUDED.imo, vessels.imo)
        """,
        mmsi, name, ship_type, imo,
    )


async def _insert_position(
    conn, mmsi: int, lat: float, lon: float,
    sog: float | None, cog: float | None,
    heading: float | None, rate_of_turn: float | None,
    status: int | None, timestamp: datetime,
):
    await conn.execute(
        """
        INSERT INTO ais_positions (vessel_id, base_datetime, position, sog, cog, heading, rate_of_turn, status)
        SELECT v.id, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), $5, $6, $7, $8, $9
        FROM vessels v WHERE v.mmsi = $1
        ON CONFLICT (vessel_id, base_datetime) DO NOTHING
        """,
        mmsi, timestamp, lon, lat, sog, cog, heading, rate_of_turn, status,
    )


async def _stream_loop():
    if not settings.aisstream_api_key:
        logger.warning("AISSTREAM_API_KEY not set — live feed disabled")
        return

    subscribe_msg = json.dumps({
        "APIKey": settings.aisstream_api_key,
        "BoundingBoxes": WEST_COAST_BBOX,
        "FilterMessageTypes": ["PositionReport"],
    })

    while True:
        try:
            async with websockets.connect(AISSTREAM_URL) as ws:
                await ws.send(subscribe_msg)
                logger.info("AISstream connected — streaming California coast")

                async for raw in ws:
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

                        time_str = meta.get("time_utc", "")
                        try:
                            # Format: "2026-07-05 07:58:45.642894217 +0000 UTC"
                            clean = time_str.split("+")[0].strip()
                            if "." in clean:
                                date_part, frac = clean.split(".")
                                frac = frac[:6]
                                clean = f"{date_part}.{frac}"
                            timestamp = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S.%f")
                        except (ValueError, AttributeError, IndexError):
                            timestamp = datetime.utcnow()

                        pool = get_pool()
                        async with pool.acquire() as conn:
                            await _upsert_vessel(conn, mmsi, name, None, None)
                            await _insert_position(conn, mmsi, lat, lon, sog, cog, heading, rate_of_turn, status, timestamp)

                    except Exception as e:
                        logger.debug(f"Skipping message: {e}")

        except (websockets.ConnectionClosed, OSError) as e:
            logger.warning(f"AISstream disconnected: {e} — reconnecting in 5s")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"AISstream error: {e} — retrying in 10s")
            await asyncio.sleep(10)


def start_stream():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_stream_loop())
        logger.info("AISstream background task started")


def stop_stream():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
        logger.info("AISstream background task stopped")
