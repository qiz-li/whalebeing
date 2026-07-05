import { useEffect, useMemo, useRef, useState } from "react";
import "mapbox-gl/dist/mapbox-gl.css";
import axios from "axios";
import "./App.css";

import { ENDPOINTS, HEATMAP_BASE_URL } from "./constants";
import { useMap } from "./hooks/useMap";
import { useShipTracks } from "./hooks/useShipTracks";
import { useLiveShips } from "./hooks/useLiveShips";
import { useAnimationClock } from "./hooks/useAnimationClock";
import { buildShipFrame, positionAt } from "./lib/shipFrames";
import { buildProjections } from "./lib/projections";
import { getWhaleFeatures } from "./lib/whaleCache";
import { calculateRisk } from "./riskCalculator";
import ControlPanel from "./components/ControlPanel";
import TimelineControls from "./components/TimelineControls";
import ShipDetailsPanel from "./components/ShipDetailsPanel";
import LiveShipPanel from "./components/LiveShipPanel";

const EMPTY_FC = { type: "FeatureCollection", features: [] };
const DAY_SECONDS = 86400;

function App() {
  const mapContainerRef = useRef();
  const [theme, setTheme] = useState("light");
  const [mode, setMode] = useState("live");
  const [startDate, setStartDate] = useState("2023-06-01");
  const [endDate, setEndDate] = useState("2023-06-02");
  const [selectedMmsi, setSelectedMmsi] = useState(null);
  const [riskScore, setRiskScore] = useState(null);

  const { ships, days, startEpoch, loading, error, load } = useShipTracks();
  const live = useLiveShips();
  const totalHours = days.length * 24;
  const { timeHours, playing, play, pause, seek } =
    useAnimationClock(totalHours);
  const { mapRef, mapReady } = useMap(mapContainerRef, theme, setSelectedMmsi);

  const dayIndex = Math.min(Math.floor(timeHours / 24), days.length - 1);
  const currentDay = days[dayIndex];
  const absEpoch = startEpoch + timeHours * 3600;

  const selectedShip = useMemo(
    () => ships.find((s) => s.mmsi === selectedMmsi) ?? null,
    [ships, selectedMmsi]
  );
  const selectedPosition = selectedShip
    ? positionAt(selectedShip.positions, absEpoch)
    : null;

  // Start live polling on mount
  useEffect(() => {
    if (mode === "live") live.start();
    return () => live.stop();
  }, [mode]);

  const handleLoad = () => {
    if (!startDate || !endDate) return;
    setSelectedMmsi(null);
    live.stop();
    setMode("historical");
    load(startDate, endDate);
  };

  const handleGoLive = () => {
    setMode("live");
    setSelectedMmsi(null);
  };

  // Start playing whenever a new range finishes loading
  useEffect(() => {
    if (totalHours > 0 && mode === "historical") play();
  }, [totalHours, play, mode]);

  // Live mode: push GeoJSON directly to ships-source + projections
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || mode !== "live" || !live.geojson) return;
    const data = selectedMmsi
      ? {
          ...live.geojson,
          features: live.geojson.features.map((f) => ({
            ...f,
            properties: {
              ...f.properties,
              selected: f.properties.mmsi === selectedMmsi,
            },
          })),
        }
      : live.geojson;
    map.getSource("ships-source")?.setData(data);
    map.getSource("projections-source")?.setData(buildProjections(live.geojson, 1));
  }, [mapRef, mapReady, mode, live.geojson, selectedMmsi]);

  // Live mode: fetch trail when a ship is clicked
  const [liveTrail, setLiveTrail] = useState(null);
  const [liveShipInfo, setLiveShipInfo] = useState(null);

  useEffect(() => {
    if (mode !== "live" || !selectedMmsi) {
      setLiveTrail(null);
      setLiveShipInfo(null);
      return;
    }
    let cancelled = false;
    axios
      .get(ENDPOINTS.VESSEL_TRAIL, { params: { mmsi: selectedMmsi, hours: 3 } })
      .then((res) => {
        if (cancelled) return;
        setLiveTrail(res.data.track);
        setLiveShipInfo(res.data);
      })
      .catch(() => {
        if (!cancelled) setLiveTrail(null);
      });
    return () => { cancelled = true; };
  }, [mode, selectedMmsi]);

  // Push trail to map
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || mode !== "live") return;
    map.getSource("trail-source")?.setData(
      liveTrail || EMPTY_FC
    );
  }, [mapRef, mapReady, mode, liveTrail]);

  // Heatmap: only in historical mode
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || mode !== "historical" || !currentDay) return;
    map
      .getSource("heatmap-source")
      ?.setData(`${HEATMAP_BASE_URL}/${currentDay}.geojson`);
  }, [mapRef, mapReady, currentDay, mode]);

  // Clear historical layers in live mode
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || mode !== "live") return;
    map.getSource("heatmap-source")?.setData(EMPTY_FC);
    map.getSource("route-source")?.setData(EMPTY_FC);
  }, [mapRef, mapReady, mode]);

  // Clear live layers in historical mode
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || mode !== "historical") return;
    map.getSource("projections-source")?.setData(EMPTY_FC);
    map.getSource("trail-source")?.setData(EMPTY_FC);
  }, [mapRef, mapReady, mode]);

  // Ship positions: every clock tick (historical mode)
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !ships.length || mode !== "historical") return;
    map
      .getSource("ships-source")
      ?.setData(buildShipFrame(ships, absEpoch, selectedMmsi));
  }, [mapRef, mapReady, ships, absEpoch, selectedMmsi, mode]);

  // Route highlight for the selected ship
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || mode !== "historical") return;
    map.getSource("route-source")?.setData(
      selectedShip
        ? {
            type: "Feature",
            properties: {},
            geometry: {
              type: "LineString",
              coordinates: selectedShip.positions.map((p) => [p[0], p[1]]),
            },
          }
        : EMPTY_FC
    );
  }, [mapRef, mapReady, selectedShip, mode]);

  // Risk for the selected ship against the current day's whale habitat
  useEffect(() => {
    if (!selectedShip || !currentDay || mode !== "historical") {
      setRiskScore(null);
      return;
    }
    let cancelled = false;
    const dayStart = startEpoch + dayIndex * DAY_SECONDS;
    const dayPositions = selectedShip.positions
      .filter((p) => p[2] >= dayStart && p[2] < dayStart + DAY_SECONDS)
      .map((p) => [p[0], p[1]]);
    getWhaleFeatures(currentDay)
      .then((whales) => calculateRisk(dayPositions, whales))
      .then((result) => {
        if (!cancelled) setRiskScore(result.riskScore);
      })
      .catch(() => {
        if (!cancelled) setRiskScore(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedShip, currentDay, dayIndex, startEpoch, mode]);

  const timeLabel = currentDay
    ? new Date(absEpoch * 1000).toLocaleString(undefined, {
        month: "long",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      })
    : "";

  const liveCount = live.geojson?.features?.length ?? 0;

  return (
    <div className={theme === "light" ? "light-theme" : "dark-theme"}>
      <div ref={mapContainerRef} className="w-full h-screen" />

      <ControlPanel
        theme={theme}
        mode={mode}
        startDate={startDate}
        endDate={endDate}
        onStartDateChange={setStartDate}
        onEndDateChange={setEndDate}
        onLoad={handleLoad}
        onGoLive={handleGoLive}
        loading={loading}
        error={error || live.error}
        liveCount={liveCount}
      />

      {selectedShip && mode === "historical" && (
        <ShipDetailsPanel
          theme={theme}
          ship={selectedShip}
          position={selectedPosition}
          riskScore={riskScore}
          onClose={() => setSelectedMmsi(null)}
        />
      )}

      {selectedMmsi && mode === "live" && liveShipInfo && (
        <LiveShipPanel
          theme={theme}
          info={liveShipInfo}
          onClose={() => setSelectedMmsi(null)}
        />
      )}

      {days.length > 0 && mode === "historical" && (
        <TimelineControls
          theme={theme}
          playing={playing}
          onPlayPause={playing ? pause : play}
          timeHours={timeHours}
          totalHours={totalHours}
          onSeek={seek}
          label={timeLabel}
        />
      )}

      <button
        onClick={() =>
          setTheme((prev) => (prev === "light" ? "dark" : "light"))
        }
        className={`absolute z-10 bottom-1 left-0 border-none px-2 py-1 text-xs ${
          theme === "light" ? "bg-[#F0F4F7]" : "bg-[#8C8D8D]"
        } text-black`}
      >
        Toggle theme (<b>{theme === "light" ? "Dark" : "Light"}</b>)
      </button>

      <div className="absolute z-10 bottom-5 right-0 bg-opacity-50 border-none px-2 py-1 text-xs bg-white text-black">
        Abrahms et al., 2019. Dynamic ensemble models. Ecol. Appl. 29(6):
        e01977
      </div>
    </div>
  );
}

export default App;
