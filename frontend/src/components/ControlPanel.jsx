import { DATA_MIN_DATE, DATA_MAX_DATE } from "../constants";

const inputStyle = (theme) => ({
  backgroundColor:
    theme === "light" ? "rgba(255, 255, 255, 0.3)" : "rgba(0, 0, 0, 0.3)",
});

function ControlPanel({
  theme,
  mode,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
  onLoad,
  onGoLive,
  loading,
  error,
  liveCount,
}) {
  return (
    <div className="absolute top-20 left-20 p-4 bg-transparent text-white rounded-lg z-10 flex flex-col gap-4">
      <h1
        className={`text-4xl font-bold ${
          theme === "light" ? "text-gray-800" : "text-white"
        }`}
        style={{ fontFamily: "Domine, serif" }}
      >
        WhaleBeing
      </h1>
      <h2
        className={`text-base font-light ${
          theme === "light" ? "text-gray-600" : "text-gray-300"
        }`}
        style={{ marginTop: "-15px" }}
      >
        Prediction model for whale-ship interactions.
      </h2>

      <div className="flex gap-2">
        <button
          onClick={onGoLive}
          className={`rounded px-3 py-1 text-sm border-none cursor-pointer ${
            mode === "live"
              ? "bg-green-600 text-white"
              : "bg-gray-300 text-gray-700"
          }`}
        >
          Live
        </button>
        <button
          onClick={() => {}}
          className={`rounded px-3 py-1 text-sm border-none ${
            mode === "historical"
              ? "bg-blue-600 text-white"
              : "bg-gray-300 text-gray-700 cursor-default"
          }`}
        >
          Historical
        </button>
      </div>

      {mode === "live" && (
        <p
          className={`text-sm ${
            theme === "light" ? "text-gray-700" : "text-gray-300"
          }`}
        >
          {liveCount > 0
            ? `${liveCount} vessels on California coast`
            : "Connecting..."}
        </p>
      )}

      {mode !== "live" && (
        <>
          <div className="flex gap-2">
            <input
              type="date"
              value={startDate}
              min={DATA_MIN_DATE}
              max={DATA_MAX_DATE}
              onChange={(e) => onStartDateChange(e.target.value)}
              className={`border rounded px-2 py-1 w-auto text-center text-sm border-gray-600 ${
                theme === "light" ? "text-black" : "text-white"
              }`}
              style={inputStyle(theme)}
            />
            <input
              type="date"
              value={endDate}
              min={DATA_MIN_DATE}
              max={DATA_MAX_DATE}
              onChange={(e) => onEndDateChange(e.target.value)}
              className={`border rounded px-2 py-1 w-auto text-center text-sm border-gray-600 ${
                theme === "light" ? "text-black" : "text-white"
              }`}
              style={inputStyle(theme)}
            />
          </div>

          <button
            onClick={onLoad}
            disabled={loading}
            className="w-1/2 border-none rounded px-2 py-1 cursor-pointer text-sm m-0 bg-gray-600 text-white disabled:opacity-50"
          >
            {loading ? "Loading..." : "Load Ships"}
          </button>
        </>
      )}

      {error && (
        <p
          className={`errorText text-sm ${
            theme === "light" ? "text-black" : "text-white"
          }`}
        >
          Error: {error}
        </p>
      )}
    </div>
  );
}

export default ControlPanel;
