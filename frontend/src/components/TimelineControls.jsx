function TimelineControls({
  theme,
  playing,
  onPlayPause,
  timeHours,
  totalHours,
  onSeek,
  label,
}) {
  return (
    <div
      className={`absolute z-10 bottom-5 left-1/2 -translate-x-1/2 flex items-center gap-3 rounded-lg px-4 py-2 w-[28rem] max-w-[90vw] ${
        theme === "light" ? "text-black" : "text-white"
      }`}
      style={{
        backgroundColor:
          theme === "light" ? "rgba(255, 255, 255, 0.7)" : "rgba(0, 0, 0, 0.6)",
      }}
    >
      <button
        onClick={onPlayPause}
        className="border-none rounded px-2 py-1 cursor-pointer text-sm bg-gray-600 text-white w-16"
      >
        {playing ? "Pause" : "Play"}
      </button>
      <input
        type="range"
        min={0}
        max={totalHours}
        step={0.1}
        value={timeHours}
        onChange={(e) => onSeek(Number(e.target.value))}
        className="flex-1 cursor-pointer"
      />
      <span className="text-xs whitespace-nowrap w-28 text-right">
        <b>{label}</b>
      </span>
    </div>
  );
}

export default TimelineControls;
