"""Shared constants for the ingest / stream / archive scripts."""

# West Coast bounding box: Baja approaches → Vancouver/BC.
LAT_MIN, LAT_MAX = 30.0, 51.0
LON_MIN, LON_MAX = -130.0, -115.0

# AISstream subscription format: [[[lat_min, lon_min], [lat_max, lon_max]]].
AISSTREAM_BBOX = [[[LAT_MIN, LON_MIN], [LAT_MAX, LON_MAX]]]

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/whalebeing"


def in_bbox(lat: float, lon: float) -> bool:
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX
