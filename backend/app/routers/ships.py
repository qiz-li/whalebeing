from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.ais_query import get_vessel_route
from app.services.searoutes import fetch_vessel_trace

router = APIRouter()


@router.get("/ship-data")
async def get_ship_data(
    imo: str = Query(None),
    mmsi: str = Query(None),
    start_date: str = Query(...),
    end_date: str = Query(...),
):
    if not imo and not mmsi:
        return JSONResponse(status_code=400, content={"error": "Provide imo or mmsi"})

    # Primary: query local PostGIS database
    if settings.use_local_ais:
        coordinates = await get_vessel_route(
            imo=imo, mmsi=mmsi, start_date=start_date, end_date=end_date
        )
        if coordinates:
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"imo": imo, "mmsi": mmsi},
                        "geometry": {
                            "type": "MultiLineString",
                            "coordinates": [coordinates],
                        },
                    }
                ],
            }

    # Fallback: SeaRoutes API (only works with IMO)
    if imo and settings.searoutes_api_key:
        result = await fetch_vessel_trace(imo, start_date, end_date)
        if result and result["status"] == 200:
            return result["data"]

    return JSONResponse(status_code=404, content={"error": "No route data found"})
