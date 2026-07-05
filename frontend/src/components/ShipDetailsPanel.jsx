const getRiskScoreColor = (score) => {
  if (score === 0) return "rgba(33,102,172,0)";
  if (score <= 0.2) return "rgb(103,169,207)";
  if (score <= 0.4) return "rgb(209,229,240)";
  if (score <= 0.6) return "rgb(253,219,199)";
  if (score <= 0.8) return "rgb(239,138,98)";
  if (score <= 1) return "rgb(178,24,43)";
  return "red";
};

function ShipDetailsPanel({ theme, ship, position, riskScore, onClose }) {
  return (
    <div
      className={`absolute top-20 right-5 z-10 rounded-lg p-4 w-64 text-sm ${
        theme === "light" ? "text-black" : "text-white"
      }`}
      style={{
        backgroundColor:
          theme === "light" ? "rgba(255, 255, 255, 0.8)" : "rgba(0, 0, 0, 0.7)",
      }}
    >
      <div className="flex justify-between items-start mb-2">
        <h3 className="font-bold text-base">{ship.name || "Unknown vessel"}</h3>
        <button
          onClick={onClose}
          className="border-none bg-transparent cursor-pointer text-inherit"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <dl className="grid grid-cols-2 gap-y-1">
        <dt className="opacity-70">MMSI</dt>
        <dd>{ship.mmsi}</dd>
        <dt className="opacity-70">IMO</dt>
        <dd>{ship.imo || "—"}</dd>
        <dt className="opacity-70">Type</dt>
        <dd>{ship.type ?? "—"}</dd>
        <dt className="opacity-70">Speed</dt>
        <dd>{position ? `${position.sog ?? "—"} kn` : "inactive"}</dd>
        <dt className="opacity-70">Course</dt>
        <dd>{position ? `${position.cog ?? "—"}°` : "inactive"}</dd>
      </dl>
      {riskScore !== null && (
        <div
          className="mt-3 p-2 rounded"
          style={{ backgroundColor: getRiskScoreColor(Number(riskScore)) }}
        >
          Risk Score: <b>{Math.round(Number(riskScore) * 100)}%</b>
        </div>
      )}
    </div>
  );
}

export default ShipDetailsPanel;
