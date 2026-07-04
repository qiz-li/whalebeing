import httpx

from app.config import settings

SEAROUTES_TRACE_URL = "https://api.searoutes.com/vessel/v2/trace"


async def fetch_vessel_trace(imo: str, start_date: str, end_date: str) -> dict | None:
    if not settings.searoutes_api_key:
        return None

    params = {
        "imo": imo,
        "departureDateTime": f"{start_date}Z",
        "arrivalDateTime": f"{end_date}Z",
    }
    headers = {"accept": "application/json", "x-api-key": settings.searoutes_api_key}

    async with httpx.AsyncClient() as client:
        response = await client.get(SEAROUTES_TRACE_URL, params=params, headers=headers)

    if response.status_code == 200:
        return {"status": 200, "data": response.json()}

    return {"status": response.status_code, "message": response.text}
