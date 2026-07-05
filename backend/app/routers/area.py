from fastapi import APIRouter, Query

from app.services.ais_query import get_ships_in_area

router = APIRouter()


@router.get("/ships-in-area")
async def ships_in_area(
    min_lat: float = Query(...),
    max_lat: float = Query(...),
    min_lon: float = Query(...),
    max_lon: float = Query(...),
    date: str = Query(...),
):
    positions = await get_ships_in_area(min_lat, max_lat, min_lon, max_lon, date)

    features = []
    for pos in positions:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "mmsi": pos["mmsi"],
                    "imo": pos["imo"],
                    "vessel_name": pos["vessel_name"],
                    "vessel_type": pos["vessel_type"],
                    "sog": pos["sog"],
                    "cog": pos["cog"],
                    "timestamp": pos["base_datetime"].isoformat(),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [pos["lon"], pos["lat"]],
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
