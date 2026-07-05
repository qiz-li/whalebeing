import { useCallback, useMemo, useRef, useState } from "react";
import axios from "axios";
import { ENDPOINTS } from "../constants";

function listDays(start, end) {
  const days = [];
  let t = Date.parse(`${start}T00:00:00Z`);
  const endT = Date.parse(`${end}T00:00:00Z`);
  while (t <= endT) {
    days.push(new Date(t).toISOString().slice(0, 10));
    t += 86400_000;
  }
  return days;
}

/**
 * Fetches all ship tracks for a date range (one request per range,
 * cached for the session). Also derives the list of days covered and
 * the range's starting epoch (UTC seconds) for the animation clock.
 */
export function useShipTracks() {
  const cacheRef = useRef(new Map());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (start, end) => {
    const key = `${start}_${end}`;
    setError("");
    const cached = cacheRef.current.get(key);
    if (cached) {
      setData(cached);
      return;
    }
    setLoading(true);
    try {
      const res = await axios.get(ENDPOINTS.SHIP_TRACKS, {
        params: { start_date: start, end_date: end },
      });
      cacheRef.current.set(key, res.data);
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const days = useMemo(
    () => (data ? listDays(data.start, data.end) : []),
    [data]
  );
  const startEpoch = useMemo(
    () => (data ? Date.parse(`${data.start}T00:00:00Z`) / 1000 : 0),
    [data]
  );

  return { ships: data?.ships ?? [], days, startEpoch, loading, error, load };
}
