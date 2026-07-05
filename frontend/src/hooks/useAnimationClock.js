import { useCallback, useEffect, useState } from "react";

const TICK_MS = 50;
const HOURS_PER_TICK = 0.1; // ~2 simulated hours per real second

/**
 * Fractional-hour animation clock over [0, totalHours).
 */
export function useAnimationClock(totalHours) {
  const [timeHours, setTimeHours] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing || totalHours <= 0) return;
    const id = setInterval(() => {
      setTimeHours((t) => (t + HOURS_PER_TICK) % totalHours);
    }, TICK_MS);
    return () => clearInterval(id);
  }, [playing, totalHours]);

  useEffect(() => {
    setTimeHours(0);
  }, [totalHours]);

  const play = useCallback(() => setPlaying(true), []);
  const pause = useCallback(() => setPlaying(false), []);
  const seek = useCallback((t) => setTimeHours(t), []);

  return { timeHours, playing, play, pause, seek };
}
