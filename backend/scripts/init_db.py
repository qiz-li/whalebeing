"""Initialize the database schema for AIS data storage.

Layout:
  - vessels: one row per vessel (mmsi is the natural identifier)
  - hourly_positions: first fix per vessel per hour, full history — serves /ship-tracks
  - ais_positions_recent: rolling ~30-day full-resolution window — serves /vessel-trail
  - latest_positions: one row per vessel, upserted by the stream worker — serves /ships-live

Full-resolution history lives in Parquet on S3 (see scripts/export_archive.py),
not in PostgreSQL.
"""

import argparse
import psycopg

DDL = """
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS vessels (
    id SERIAL PRIMARY KEY,
    mmsi BIGINT NOT NULL UNIQUE,
    imo VARCHAR(20),
    vessel_name VARCHAR(255),
    call_sign VARCHAR(20),
    vessel_type INT,
    length REAL,
    width REAL,
    draft REAL,
    cargo INT
);

CREATE INDEX IF NOT EXISTS idx_vessels_imo ON vessels (imo) WHERE imo IS NOT NULL;

CREATE TABLE IF NOT EXISTS hourly_positions (
    vessel_id INT NOT NULL REFERENCES vessels(id),
    hour TIMESTAMP NOT NULL,
    position GEOMETRY(Point, 4326) NOT NULL,
    sog REAL,
    cog REAL,
    PRIMARY KEY (vessel_id, hour)
);

CREATE INDEX IF NOT EXISTS idx_hourly_geom ON hourly_positions USING GIST (position);
CREATE INDEX IF NOT EXISTS idx_hourly_hour ON hourly_positions (hour);

CREATE TABLE IF NOT EXISTS ais_positions_recent (
    vessel_id INT NOT NULL REFERENCES vessels(id),
    base_datetime TIMESTAMP NOT NULL,
    position GEOMETRY(Point, 4326) NOT NULL,
    sog REAL,
    cog REAL,
    heading REAL,
    rate_of_turn REAL,
    status INT,
    PRIMARY KEY (vessel_id, base_datetime)
);

CREATE INDEX IF NOT EXISTS idx_recent_datetime ON ais_positions_recent (base_datetime);

CREATE TABLE IF NOT EXISTS latest_positions (
    vessel_id INT PRIMARY KEY REFERENCES vessels(id),
    base_datetime TIMESTAMP NOT NULL,
    position GEOMETRY(Point, 4326) NOT NULL,
    sog REAL,
    cog REAL,
    heading REAL
);
"""


def main():
    parser = argparse.ArgumentParser(description="Initialize the WhaleBeing database")
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@localhost:5432/whalebeing",
        help="PostgreSQL connection string",
    )
    args = parser.parse_args()

    with psycopg.connect(args.database_url) as conn:
        conn.execute(DDL)
        conn.commit()

    print("Database initialized successfully.")


if __name__ == "__main__":
    main()
