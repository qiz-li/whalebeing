import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import { MAPBOX_TOKEN, MAP_STYLES } from "../constants";

const EMPTY_FC = { type: "FeatureCollection", features: [] };

function addLayers(map, theme) {
  map.addSource("heatmap-source", { type: "geojson", data: EMPTY_FC });
  map.addLayer({
    id: "heatmap-layer",
    type: "heatmap",
    source: "heatmap-source",
    paint: {
      "heatmap-weight": ["get", "weight"],
      "heatmap-intensity": 1,
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0,
        "rgba(33,102,172,0)",
        0.2,
        "rgb(103,169,207)",
        0.4,
        "rgb(209,229,240)",
        0.6,
        "rgb(253,219,199)",
        0.8,
        "rgb(239,138,98)",
        1,
        "rgb(178,24,43)",
      ],
      "heatmap-radius": 20,
      "heatmap-opacity": 0.8,
    },
  });

  map.addSource("route-source", { type: "geojson", data: EMPTY_FC });
  map.addLayer({
    id: "route-layer",
    type: "line",
    source: "route-source",
    layout: {
      "line-join": "round",
      "line-cap": "round",
    },
    paint: {
      "line-color": theme === "light" ? "#3b5f7d" : "#fff",
      "line-width": 3,
      "line-blur": 2,
      "line-opacity": 0.8,
    },
  });

  map.addSource("projections-source", { type: "geojson", data: EMPTY_FC });
  map.addLayer({
    id: "projections-layer",
    type: "line",
    source: "projections-source",
    paint: {
      "line-color": theme === "light" ? "#dc2626" : "#fbbf24",
      "line-width": 1.5,
      "line-dasharray": [3, 3],
      "line-opacity": 0.6,
    },
  });

  map.addSource("trail-source", { type: "geojson", data: EMPTY_FC });
  map.addLayer({
    id: "trail-layer",
    type: "line",
    source: "trail-source",
    paint: {
      "line-color": "#f59e0b",
      "line-width": 2.5,
      "line-opacity": 0.8,
    },
  });

  map.addSource("ships-source", { type: "geojson", data: EMPTY_FC });
  map.addLayer({
    id: "ships-layer",
    type: "circle",
    source: "ships-source",
    paint: {
      "circle-radius": [
        "case",
        ["boolean", ["get", "selected"], false],
        7,
        4,
      ],
      "circle-color": [
        "case",
        ["boolean", ["get", "selected"], false],
        "#f59e0b",
        theme === "light" ? "#1d4ed8" : "#7dd3fc",
      ],
      "circle-stroke-width": 1,
      "circle-stroke-color": theme === "light" ? "#ffffff" : "#1f2937",
      "circle-opacity": 0.9,
    },
  });
}

/**
 * Creates the Mapbox map exactly once. Theme changes swap the style and
 * re-add sources/layers instead of recreating the map. `mapReady` is a
 * counter bumped on every (re)load of the style so consumers know to
 * re-push their source data.
 */
export function useMap(containerRef, theme, onShipClick) {
  const mapRef = useRef(null);
  const [mapReady, setMapReady] = useState(0);
  const onShipClickRef = useRef(onShipClick);
  onShipClickRef.current = onShipClick;
  const themeRef = useRef(theme);

  useEffect(() => {
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: MAP_STYLES[themeRef.current],
      center: [-122.0, 38.5],
      zoom: 4.5,
    });
    mapRef.current = map;

    map.on("load", () => {
      addLayers(map, themeRef.current);
      setMapReady((v) => v + 1);
    });

    map.on("click", (e) => {
      if (!map.getLayer("ships-layer")) return;
      const features = map.queryRenderedFeatures(e.point, {
        layers: ["ships-layer"],
      });
      onShipClickRef.current(
        features.length ? Number(features[0].properties.mmsi) : null
      );
    });
    map.on("mouseenter", "ships-layer", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "ships-layer", () => {
      map.getCanvas().style.cursor = "";
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [containerRef]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || themeRef.current === theme) return;
    themeRef.current = theme;
    map.setStyle(MAP_STYLES[theme]);
    map.once("style.load", () => {
      addLayers(map, theme);
      setMapReady((v) => v + 1);
    });
  }, [theme]);

  return { mapRef, mapReady };
}
