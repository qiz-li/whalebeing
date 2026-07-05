import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { ENDPOINTS } from "../constants";

const POLL_INTERVAL = 10_000;

export function useLiveShips() {
  const [geojson, setGeojson] = useState(null);
  const [error, setError] = useState("");
  const intervalRef = useRef(null);

  const fetch_ = useCallback(async () => {
    try {
      const res = await axios.get(ENDPOINTS.SHIPS_LIVE);
      setGeojson(res.data);
      setError("");
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    }
  }, []);

  const start = useCallback(() => {
    fetch_();
    intervalRef.current = setInterval(fetch_, POLL_INTERVAL);
  }, [fetch_]);

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => () => stop(), [stop]);

  return { geojson, error, start, stop };
}
