import { HEATMAP_BASE_URL } from "../constants";

const cache = new Map();

/**
 * Fetch a day's whale habitat features once and memoize the promise.
 * Only used for risk calculation; the heatmap layer loads the geojson
 * URLs directly.
 */
export function getWhaleFeatures(day) {
  if (!cache.has(day)) {
    const promise = fetch(`${HEATMAP_BASE_URL}/${day}.geojson`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to fetch whale data for ${day}`);
        return res.json();
      })
      .then((geojson) => geojson.features);
    promise.catch(() => cache.delete(day));
    cache.set(day, promise);
  }
  return cache.get(day);
}
