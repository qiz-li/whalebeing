function LiveShipPanel({ theme, info, onClose }) {
  const latest = info.positions?.length
    ? info.positions[info.positions.length - 1]
    : null;

  return (
    <div
      className={`absolute top-20 right-5 z-10 rounded-lg p-4 w-64 text-sm ${
        theme === "light" ? "text-black" : "text-white"
      }`}
      style={{
        backgroundColor:
          theme === "light"
            ? "rgba(255, 255, 255, 0.8)"
            : "rgba(0, 0, 0, 0.7)",
      }}
    >
      <div className="flex justify-between items-start mb-2">
        <h3 className="font-bold text-base">MMSI {info.mmsi}</h3>
        <button
          onClick={onClose}
          className="border-none bg-transparent cursor-pointer text-inherit"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      {latest && (
        <dl className="grid grid-cols-2 gap-y-1">
          <dt className="opacity-70">Speed</dt>
          <dd>{latest.sog != null ? `${latest.sog.toFixed(1)} kn` : "—"}</dd>
          <dt className="opacity-70">Course</dt>
          <dd>{latest.cog != null ? `${latest.cog.toFixed(0)}°` : "—"}</dd>
          <dt className="opacity-70">Heading</dt>
          <dd>
            {latest.heading != null ? `${latest.heading.toFixed(0)}°` : "—"}
          </dd>
          <dt className="opacity-70">Last fix</dt>
          <dd>
            {new Date(latest.timestamp + "Z").toLocaleTimeString(undefined, {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </dd>
          <dt className="opacity-70">Trail pts</dt>
          <dd>{info.positions.length}</dd>
        </dl>
      )}
      {!latest && <p className="opacity-70">No recent positions</p>}
    </div>
  );
}

export default LiveShipPanel;
