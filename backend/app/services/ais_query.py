from datetime import datetime, timedelta, timezone

from app.db import get_pool


def _parse_dt(s: str) -> datetime:
    """Parse a datetime string, tolerating various formats from the frontend."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


async def get_vessel_trail(mmsi: int, hours: int = 3) -> list[dict]:
    """Return recent positions for a single vessel (last N hours)."""
    pool = get_pool()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)

    query = """
        SELECT ST_X(p.position) AS lon, ST_Y(p.position) AS lat,
               p.base_datetime, p.sog, p.cog, p.heading
        FROM ais_positions p
        JOIN vessels v ON p.vessel_id = v.id
        WHERE v.mmsi = $1
          AND p.base_datetime >= $2
        ORDER BY p.base_datetime
    """
    rows = await pool.fetch(query, mmsi, cutoff)
    return [dict(row) for row in rows]


async def get_live_ships(minutes: int = 5) -> list[dict]:
    """Return the most recent position for each vessel seen in the last N minutes."""
    pool = get_pool()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)

    query = """
        SELECT DISTINCT ON (p.vessel_id)
               v.mmsi, v.imo, v.vessel_name, v.vessel_type,
               ST_X(p.position) AS lon, ST_Y(p.position) AS lat,
               p.base_datetime, p.sog, p.cog, p.heading
        FROM ais_positions p
        JOIN vessels v ON p.vessel_id = v.id
        WHERE p.base_datetime >= $1
        ORDER BY p.vessel_id, p.base_datetime DESC
    """
    rows = await pool.fetch(query, cutoff)
    return [dict(row) for row in rows]


async def get_ship_tracks(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    limit: int = 500,
) -> list[dict]:
    """Return per-ship hourly tracks within a bounding box and date range.

    Positions are snapped to the first AIS fix in each hour. Each ship dict:
    {mmsi, imo, name, type, positions: [[lon, lat, epochSeconds, sog, cog], ...]}
    """
    pool = get_pool()
    start_dt = _parse_dt(start_date)
    end_dt = _parse_dt(end_date) + timedelta(days=1)

    query = """
        SELECT DISTINCT ON (p.vessel_id, date_trunc('hour', p.base_datetime))
               v.mmsi, v.imo, v.vessel_name, v.vessel_type,
               ST_X(p.position) AS lon, ST_Y(p.position) AS lat,
               date_trunc('hour', p.base_datetime) AS hour_bucket,
               p.sog, p.cog
        FROM ais_positions p
        JOIN vessels v ON p.vessel_id = v.id
        WHERE p.position && ST_MakeEnvelope($1, $2, $3, $4, 4326)
          AND p.base_datetime >= $5
          AND p.base_datetime < $6
        ORDER BY p.vessel_id, date_trunc('hour', p.base_datetime), p.base_datetime
    """
    rows = await pool.fetch(query, min_lon, min_lat, max_lon, max_lat, start_dt, end_dt)

    epoch = datetime(1970, 1, 1)
    ships: dict[int, dict] = {}
    for row in rows:
        ship = ships.get(row["mmsi"])
        if ship is None:
            ship = ships[row["mmsi"]] = {
                "mmsi": row["mmsi"],
                "imo": row["imo"],
                "name": row["vessel_name"],
                "type": row["vessel_type"],
                "positions": [],
            }
        ship["positions"].append(
            [
                round(row["lon"], 5),
                round(row["lat"], 5),
                int((row["hour_bucket"] - epoch).total_seconds()),
                row["sog"],
                row["cog"],
            ]
        )

    tracks = sorted(ships.values(), key=lambda s: len(s["positions"]), reverse=True)
    return tracks[:limit]
