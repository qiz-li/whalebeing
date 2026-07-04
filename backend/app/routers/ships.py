from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.searoutes import fetch_vessel_trace

router = APIRouter()


@router.get("/ship-data")
async def get_ship_data(
    imo: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
):
    result = await fetch_vessel_trace(imo, start_date, end_date)

    if result is None:
        return JSONResponse(status_code=500, content={"error": "SEAROUTES_API_KEY not configured"})

    if result["status"] == 200:
        return result["data"]

    return JSONResponse(
        status_code=result["status"],
        content={"error": str(result["status"]), "message": result["message"]},
    )
