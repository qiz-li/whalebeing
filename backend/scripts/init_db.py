"""Initialize the database schema for AIS data storage."""

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

CREATE TABLE IF NOT EXISTS ais_positions (
    id BIGSERIAL PRIMARY KEY,
    vessel_id INT NOT NULL REFERENCES vessels(id),
    base_datetime TIMESTAMP NOT NULL,
    position GEOMETRY(Point, 4326) NOT NULL,
    sog REAL,
    cog REAL,
    heading REAL,
    rate_of_turn REAL,
    status INT,
    transceiver_class CHAR(1),
    UNIQUE (vessel_id, base_datetime)
);

CREATE INDEX IF NOT EXISTS idx_positions_geom ON ais_positions USING GIST (position);
CREATE INDEX IF NOT EXISTS idx_positions_vessel_time ON ais_positions (vessel_id, base_datetime);
CREATE INDEX IF NOT EXISTS idx_positions_datetime ON ais_positions (base_datetime);
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
