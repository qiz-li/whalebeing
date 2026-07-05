export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;

export const ENDPOINTS = {
  SHIP_TRACKS: `${API_BASE_URL}/ship-tracks`,
  SHIPS_LIVE: `${API_BASE_URL}/ships-live`,
  VESSEL_TRAIL: `${API_BASE_URL}/vessel-trail`,
};

export const HEATMAP_BASE_URL = "/data/daily_geojsons";

// Whale habitat geojsons only exist for 2023, days 1-28 of each month
export const DATA_MIN_DATE = "2023-01-01";
export const DATA_MAX_DATE = "2023-12-28";

export const MAP_STYLES = {
  light: "mapbox://styles/gordon111/cm5ti9unu005501rw39yr9q7o",
  dark: "mapbox://styles/mapbox/dark-v10",
};
