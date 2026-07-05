from datetime import datetime, timedelta

from app.db import get_pool


def _parse_dt(s: str) -> datetime:
    """Parse a datetime string, tolerating various formats from the frontend."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


def _normalize_imo(imo: str) -> str:
    """Ensure IMO has the 'IMO' prefix to match DB storage."""
    imo = imo.strip()
    if not imo.upper().startswith("IMO"):
        return f"IMO{imo}"
    return imo.upper()


async def get_vessel_route(
    imo: str | None, mmsi: str | None, start_date: str, end_date: str
) -> list[list[float]]:
    """Return ordered [[lon, lat], ...] pairs for a vessel in a date range."""
    pool = get_pool()

    start_dt = _parse_dt(start_date)
    end_dt = _parse_dt(end_date)
    # If start and end are the same timestamp, extend end to cover the full day
    if end_dt <= start_dt:
        end_dt = start_dt.replace(hour=23, minute=59, second=59)

    if imo:
        normalized_imo = _normalize_imo(imo)
        query = """
            SELECT ST_X(p.position) AS lon, ST_Y(p.position) AS lat
            FROM ais_positions p
            JOIN vessels v ON p.vessel_id = v.id
            WHERE v.imo = $1
              AND p.base_datetime >= $2
              AND p.base_datetime <= $3
            ORDER BY p.base_datetime
        """
        rows = await pool.fetch(query, normalized_imo, start_dt, end_dt)
    elif mmsi:
        query = """
            SELECT ST_X(p.position) AS lon, ST_Y(p.position) AS lat
            FROM ais_positions p
            JOIN vessels v ON p.vessel_id = v.id
            WHERE v.mmsi = $1
              AND p.base_datetime >= $2
              AND p.base_datetime <= $3
            ORDER BY p.base_datetime
        """
        rows = await pool.fetch(query, int(mmsi), start_dt, end_dt)
    else:
        return []

    return [[row["lon"], row["lat"]] for row in rows]


async def get_ships_in_area(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float, target_date: str
) -> list[dict]:
    """Return all vessel positions within a bounding box on a given date."""
    pool = get_pool()
    date_start = _parse_dt(target_date)
    date_end = datetime(date_start.year, date_start.month, date_start.day, 23, 59, 59)

    query = """
        SELECT v.mmsi, v.imo, v.vessel_name, v.vessel_type,
               ST_X(p.position) AS lon, ST_Y(p.position) AS lat,
               p.base_datetime, p.sog, p.cog
        FROM ais_positions p
        JOIN vessels v ON p.vessel_id = v.id
        WHERE p.position && ST_MakeEnvelope($1, $2, $3, $4, 4326)
          AND p.base_datetime >= $5
          AND p.base_datetime <= $6
        ORDER BY p.base_datetime
    """
    rows = await pool.fetch(query, min_lon, min_lat, max_lon, max_lat, date_start, date_end)
    return [dict(row) for row in rows]
