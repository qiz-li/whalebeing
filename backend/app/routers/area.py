from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.ais_query import get_live_ships, get_ship_tracks, get_vessel_trail

router = APIRouter()


@router.get("/vessel-trail")
async def vessel_trail(mmsi: int = Query(...), hours: int = Query(3, ge=1, le=24)):
    """Return recent track for a single vessel."""
    positions = await get_vessel_trail(mmsi, hours)
    coordinates = [[pos["lon"], pos["lat"]] for pos in positions]
    return {
        "mmsi": mmsi,
        "positions": [
            {
                "lon": pos["lon"],
                "lat": pos["lat"],
                "sog": pos["sog"],
                "cog": pos["cog"],
                "heading": pos["heading"],
                "timestamp": pos["base_datetime"].isoformat(),
            }
            for pos in positions
        ],
        "track": {
            "type": "Feature",
            "properties": {"mmsi": mmsi},
            "geometry": {"type": "LineString", "coordinates": coordinates},
        } if len(coordinates) >= 2 else None,
    }


@router.get("/ships-live")
async def ships_live(minutes: int = Query(5, ge=1, le=30)):
    """Return latest position for every vessel seen in the last N minutes."""
    positions = await get_live_ships(minutes)
    features = []
    for pos in positions:
        features.append({
            "type": "Feature",
            "properties": {
                "mmsi": pos["mmsi"],
                "imo": pos["imo"],
                "name": pos["vessel_name"],
                "type": pos["vessel_type"],
                "sog": pos["sog"],
                "cog": pos["cog"],
                "heading": pos["heading"],
                "timestamp": pos["base_datetime"].isoformat(),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [pos["lon"], pos["lat"]],
            },
        })
    return {"type": "FeatureCollection", "features": features}

MAX_RANGE_DAYS = 14

# Default bbox matches the NOAA ingest area (California coast)
DEFAULT_MIN_LAT = 30.0
DEFAULT_MAX_LAT = 51.0
DEFAULT_MIN_LON = -130.0
DEFAULT_MAX_LON = -115.0


@router.get("/ship-tracks")
async def ship_tracks(
    start_date: str = Query(...),
    end_date: str = Query(...),
    min_lat: float = Query(DEFAULT_MIN_LAT),
    max_lat: float = Query(DEFAULT_MAX_LAT),
    min_lon: float = Query(DEFAULT_MIN_LON),
    max_lon: float = Query(DEFAULT_MAX_LON),
    limit: int = Query(500, ge=1, le=2000),
):
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Dates must be YYYY-MM-DD")
    if end < start:
        raise HTTPException(status_code=422, detail="end_date must be >= start_date")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422, detail=f"Date range must be at most {MAX_RANGE_DAYS} days"
        )

    ships = await get_ship_tracks(
        min_lat, max_lat, min_lon, max_lon, start_date, end_date, limit
    )
    return {"start": start_date, "end": end_date, "ships": ships}
