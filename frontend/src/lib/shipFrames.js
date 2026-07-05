// A ship with no fix for over 3 hours is considered inactive at that time
const MAX_GAP_SECONDS = 3 * 3600;

/**
 * Find a ship's interpolated position at `epochSeconds`, or null if the
 * ship is not active then. `positions` is the sorted array of
 * [lon, lat, epochSeconds, sog, cog] from the API.
 */
export function positionAt(positions, epochSeconds) {
  const n = positions.length;
  if (n === 0) return null;
  if (epochSeconds < positions[0][2] || epochSeconds > positions[n - 1][2]) {
    return null;
  }

  // Binary search: last index with time <= epochSeconds
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (positions[mid][2] <= epochSeconds) lo = mid;
    else hi = mid - 1;
  }

  const a = positions[lo];
  if (a[2] === epochSeconds || lo === n - 1) {
    return { lon: a[0], lat: a[1], sog: a[3], cog: a[4] };
  }

  const b = positions[lo + 1];
  if (b[2] - a[2] > MAX_GAP_SECONDS) return null;

  const f = (epochSeconds - a[2]) / (b[2] - a[2]);
  return {
    lon: a[0] + (b[0] - a[0]) * f,
    lat: a[1] + (b[1] - a[1]) * f,
    sog: a[3],
    cog: a[4],
  };
}

/**
 * Build the GeoJSON FeatureCollection of all active ship positions for
 * one animation frame.
 */
export function buildShipFrame(ships, epochSeconds, selectedMmsi) {
  const features = [];
  for (const ship of ships) {
    const pos = positionAt(ship.positions, epochSeconds);
    if (!pos) continue;
    features.push({
      type: "Feature",
      properties: {
        mmsi: ship.mmsi,
        name: ship.name,
        sog: pos.sog,
        cog: pos.cog,
        selected: ship.mmsi === selectedMmsi,
      },
      geometry: { type: "Point", coordinates: [pos.lon, pos.lat] },
    });
  }
  return { type: "FeatureCollection", features };
}
