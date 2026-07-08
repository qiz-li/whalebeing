"""Shared helpers for the full-resolution AIS Parquet archive.

The archive is self-contained (keyed by mmsi, no database ids) so it stays
usable regardless of what happens to the PostgreSQL instance. Layout:

    <archive-uri>/source=<noaa|live|historic>/year=YYYY/month=MM[/day=DD].parquet

<archive-uri> is either s3://bucket/prefix or a local directory (for tests).
Query with DuckDB, e.g.:

    SELECT * FROM read_parquet('s3://bucket/ais/source=*/year=*/*.parquet')
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema([
    ("mmsi", pa.int64()),
    ("base_datetime", pa.timestamp("us")),
    ("lon", pa.float64()),
    ("lat", pa.float64()),
    ("sog", pa.float32()),
    ("cog", pa.float32()),
    ("heading", pa.float32()),
    ("rate_of_turn", pa.float32()),
    ("status", pa.int32()),
])

COLUMNS = [field.name for field in SCHEMA]


def open_writer(path: Path | str) -> pq.ParquetWriter:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return pq.ParquetWriter(path, SCHEMA, compression="zstd")


def batch_from_columns(cols: dict[str, list]) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [pa.array(cols[name], type=SCHEMA.field(name).type) for name in COLUMNS],
        schema=SCHEMA,
    )


def new_column_buffers() -> dict[str, list]:
    return {name: [] for name in COLUMNS}


def store_file(local_path: Path, archive_uri: str, rel_key: str) -> str:
    """Move a finished Parquet file into the archive. Returns the destination URI."""
    if archive_uri.startswith("s3://"):
        import boto3

        bucket, _, prefix = archive_uri[5:].partition("/")
        key = f"{prefix.rstrip('/')}/{rel_key}" if prefix else rel_key
        boto3.client("s3").upload_file(str(local_path), bucket, key)
        local_path.unlink()
        return f"s3://{bucket}/{key}"

    dest = Path(archive_uri) / rel_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    local_path.replace(dest)
    return str(dest)


def parquet_row_count(uri: str) -> int:
    """Row count of one archived Parquet file (reads footer metadata only)."""
    if uri.startswith("s3://"):
        import boto3

        bucket, _, key = uri[5:].partition("/")
        import io

        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return pq.ParquetFile(io.BytesIO(obj["Body"].read())).metadata.num_rows
    return pq.ParquetFile(uri).metadata.num_rows
