const KNOTS_TO_KMH = 1.852;
const EARTH_RADIUS_KM = 6371;
const DEG_TO_RAD = Math.PI / 180;
const RAD_TO_DEG = 180 / Math.PI;

/**
 * Given a starting point, course over ground (degrees), and speed (knots),
 * project a destination point after `hours` of travel.
 */
function projectPoint(lon, lat, cogDeg, sogKnots, hours) {
  if (!sogKnots || sogKnots < 0.5 || cogDeg == null) return null;

  const distKm = sogKnots * KNOTS_TO_KMH * hours;
  const angularDist = distKm / EARTH_RADIUS_KM;
  const bearing = cogDeg * DEG_TO_RAD;
  const lat1 = lat * DEG_TO_RAD;
  const lon1 = lon * DEG_TO_RAD;

  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDist) +
      Math.cos(lat1) * Math.sin(angularDist) * Math.cos(bearing)
  );
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angularDist) * Math.cos(lat1),
      Math.cos(angularDist) - Math.sin(lat1) * Math.sin(lat2)
    );

  return [lon2 * RAD_TO_DEG, lat2 * RAD_TO_DEG];
}

/**
 * Build a GeoJSON FeatureCollection of projected course lines for all
 * moving vessels. Each line goes from current position to projected
 * position after `projectionHours`.
 */
export function buildProjections(geojson, projectionHours = 1) {
  if (!geojson || !geojson.features) {
    return { type: "FeatureCollection", features: [] };
  }

  const features = [];
  for (const feature of geojson.features) {
    const { sog, cog, mmsi, name } = feature.properties;
    const [lon, lat] = feature.geometry.coordinates;

    const dest = projectPoint(lon, lat, cog, sog, projectionHours);
    if (!dest) continue;

    features.push({
      type: "Feature",
      properties: { mmsi, name, sog, cog },
      geometry: {
        type: "LineString",
        coordinates: [[lon, lat], dest],
      },
    });
  }

  return { type: "FeatureCollection", features };
}
