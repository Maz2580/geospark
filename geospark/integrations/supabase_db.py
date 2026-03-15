"""
Supabase Database Integration.

Uses Supabase's PostgreSQL (with PostGIS extension) as the spatial backend.
Free tier provides: 500MB database, 50K monthly active users, 1GB file storage.

Supabase is ideal for GeoSpark because:
1. Built on PostgreSQL (supports PostGIS natively)
2. Free tier is generous for development
3. Real-time subscriptions for live spatial data
4. REST API auto-generated from schema
5. Easy to scale when needed
"""

from __future__ import annotations

import os
from typing import Any


class SupabaseBackend:
    """
    Supabase spatial database backend for GeoSpark.

    Stores spatial features, knowledge graph data, and query cache
    in Supabase's PostgreSQL database with PostGIS extension.
    """

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        db_url: str | None = None,
    ):
        self.url = url or os.getenv("SUPABASE_URL", "")
        self.key = key or os.getenv("SUPABASE_KEY", "")
        self.db_url = db_url or os.getenv("SUPABASE_DB_URL", "")

        if not self.url or not self.key:
            raise ValueError(
                "Supabase URL and key required. Set SUPABASE_URL and SUPABASE_KEY env vars.\n"
                "Get these from: https://supabase.com/dashboard → your project → Settings → API"
            )

        self._client = None

    @property
    def client(self) -> Any:
        """Lazy-load Supabase client."""
        if self._client is None:
            try:
                from supabase import create_client
                self._client = create_client(self.url, self.key)
            except ImportError as e:
                raise ImportError(
                    "supabase package required: pip install supabase"
                ) from e
        return self._client

    async def initialize_schema(self) -> None:
        """
        Create the GeoSpark tables in Supabase.

        Run this once to set up the database schema.
        Requires PostGIS extension to be enabled in Supabase.
        """
        # These SQL statements should be run in Supabase SQL Editor
        # (PostGIS must be enabled first via Extensions page)
        schema_sql = self.get_schema_sql()
        print("Run the following SQL in your Supabase SQL Editor:")
        print("=" * 60)
        print(schema_sql)
        print("=" * 60)

    @staticmethod
    def get_schema_sql() -> str:
        """Return SQL to create GeoSpark schema in Supabase."""
        return """
-- Enable PostGIS extension (do this first in Supabase Dashboard → Database → Extensions)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Spatial features table
CREATE TABLE IF NOT EXISTS spatial_features (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    geometry GEOMETRY NOT NULL,
    properties JSONB DEFAULT '{}',
    category TEXT,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Spatial index for fast queries
CREATE INDEX IF NOT EXISTS idx_spatial_features_geom
    ON spatial_features USING GIST (geometry);

-- Index for category filtering
CREATE INDEX IF NOT EXISTS idx_spatial_features_category
    ON spatial_features (category);

-- Query cache table
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key TEXT PRIMARY KEY,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Spatial knowledge graph (relationships between features)
CREATE TABLE IF NOT EXISTS spatial_relations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    feature_a_id UUID REFERENCES spatial_features(id),
    feature_b_id UUID REFERENCES spatial_features(id),
    relation_type TEXT NOT NULL, -- contains, intersects, near, etc.
    distance_m DOUBLE PRECISION,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Benchmark results storage
CREATE TABLE IF NOT EXISTS benchmark_results (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    benchmark_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    details JSONB DEFAULT '{}',
    run_at TIMESTAMPTZ DEFAULT NOW()
);

-- Row Level Security (enable for production)
-- ALTER TABLE spatial_features ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE query_cache ENABLE ROW LEVEL SECURITY;

-- Function: Find features within radius
CREATE OR REPLACE FUNCTION find_within_radius(
    center_lon DOUBLE PRECISION,
    center_lat DOUBLE PRECISION,
    radius_meters DOUBLE PRECISION,
    feature_category TEXT DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    geometry GEOMETRY,
    properties JSONB,
    category TEXT,
    distance_m DOUBLE PRECISION
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        sf.id,
        sf.geometry,
        sf.properties,
        sf.category,
        ST_Distance(
            sf.geometry::geography,
            ST_SetSRID(ST_MakePoint(center_lon, center_lat), 4326)::geography
        ) as distance_m
    FROM spatial_features sf
    WHERE ST_DWithin(
        sf.geometry::geography,
        ST_SetSRID(ST_MakePoint(center_lon, center_lat), 4326)::geography,
        radius_meters
    )
    AND (feature_category IS NULL OR sf.category = feature_category)
    ORDER BY distance_m;
END;
$$ LANGUAGE plpgsql;

-- Function: Check topological relationship
CREATE OR REPLACE FUNCTION check_spatial_relation(
    geom_a GEOMETRY,
    geom_b GEOMETRY,
    relation TEXT
)
RETURNS BOOLEAN AS $$
BEGIN
    CASE relation
        WHEN 'contains' THEN RETURN ST_Contains(geom_a, geom_b);
        WHEN 'intersects' THEN RETURN ST_Intersects(geom_a, geom_b);
        WHEN 'within' THEN RETURN ST_Within(geom_a, geom_b);
        WHEN 'touches' THEN RETURN ST_Touches(geom_a, geom_b);
        WHEN 'crosses' THEN RETURN ST_Crosses(geom_a, geom_b);
        WHEN 'overlaps' THEN RETURN ST_Overlaps(geom_a, geom_b);
        WHEN 'disjoint' THEN RETURN ST_Disjoint(geom_a, geom_b);
        ELSE RAISE EXCEPTION 'Unknown relation: %', relation;
    END CASE;
END;
$$ LANGUAGE plpgsql;
"""

    def store_feature(
        self,
        geometry: dict[str, Any],
        properties: dict[str, Any] | None = None,
        category: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Store a spatial feature in Supabase."""

        data = {
            "geometry": f"SRID=4326;{self._geojson_to_wkt(geometry)}",
            "properties": properties or {},
            "category": category,
            "source": source,
        }

        result = self.client.table("spatial_features").insert(data).execute()
        return result.data[0] if result.data else {}

    def find_within(
        self,
        lon: float,
        lat: float,
        radius_m: float,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find features within radius using PostGIS."""
        result = self.client.rpc(
            "find_within_radius",
            {
                "center_lon": lon,
                "center_lat": lat,
                "radius_meters": radius_m,
                "feature_category": category,
            },
        ).execute()
        return result.data or []

    @staticmethod
    def _geojson_to_wkt(geojson: dict[str, Any]) -> str:
        """Convert GeoJSON geometry to WKT for PostGIS storage."""
        from shapely.geometry import shape
        return shape(geojson).wkt


def print_setup_instructions() -> None:
    """Print step-by-step Supabase setup instructions."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║           SUPABASE SETUP FOR GEOSPARK                       ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  1. Go to https://supabase.com/dashboard                     ║
║                                                              ║
║  2. Open your project (or create a new one)                  ║
║                                                              ║
║  3. Enable PostGIS:                                          ║
║     → Database → Extensions → search "postgis" → Enable     ║
║                                                              ║
║  4. Get your credentials:                                    ║
║     → Settings → API                                         ║
║     → Copy "Project URL" → paste as SUPABASE_URL             ║
║     → Copy "anon/public key" → paste as SUPABASE_KEY         ║
║                                                              ║
║  5. Get direct DB connection (optional):                     ║
║     → Settings → Database → Connection string → URI          ║
║     → paste as SUPABASE_DB_URL                               ║
║                                                              ║
║  6. Run the schema SQL:                                      ║
║     → SQL Editor → New query                                 ║
║     → Paste the output of:                                   ║
║       python -c "from geospark.integrations.supabase_db \\    ║
║         import SupabaseBackend; \\                             ║
║         print(SupabaseBackend.get_schema_sql())"             ║
║     → Click "Run"                                            ║
║                                                              ║
║  7. Update .env with your credentials                        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    print_setup_instructions()
