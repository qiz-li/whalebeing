import { getDistance } from "geolib";

// Calculate Risk Score
export async function calculateRisk(
  shipPoints,
  whaleData,
  spatialThreshold = 50000
) {
  if (!shipPoints.length || !whaleData.length) {
    return { riskScore: 0, details: "No data available for calculation" };
  }

  let maxRisk = 0;

  // Loop through each ship point
  for (const shipPoint of shipPoints) {
    const [shipLon, shipLat] = shipPoint;

    // Check each whale data point
    for (const whale of whaleData) {
      const {
        geometry: {
          coordinates: [whaleLon, whaleLat],
        },
        properties: { weight },
      } = whale;

      // Calculate spatial distance
      const distance = getDistance(
        { latitude: shipLat, longitude: shipLon },
        { latitude: whaleLat, longitude: whaleLon }
      );

      if (distance <= spatialThreshold) {
        if (weight > maxRisk) {
          maxRisk = weight;
        }
      }
    }
  }

  // Scale risk score for better readability
  //   const scaledRiskScore = totalRisk * 1_000_000;
  const scaledRiskScore = Math.max(0, maxRisk - 0.15);

  return {
    riskScore: scaledRiskScore.toFixed(2), // Return scaled risk score
    details: `Risk calculated with ${shipPoints.length} ship points and ${whaleData.length} whale points.`,
  };
}
