import type { AthPriceZoneOverlay } from "../chartTypes";

interface AthPriceZonesOverlayProps {
  overlays: AthPriceZoneOverlay[];
}

export function AthPriceZonesOverlay({ overlays }: AthPriceZonesOverlayProps) {
  if (overlays.length === 0) {
    return null;
  }

  return (
    <div className="ath-price-zone-layer" aria-hidden="true">
      {overlays.map((overlay) => (
        <div
          className="ath-price-zone"
          key={overlay.id}
          style={{
            top: overlay.top,
            height: overlay.height,
            backgroundColor: overlay.color
          }}
          title={`${overlay.label} max ${overlay.maxLotEquivalents}`}
        />
      ))}
    </div>
  );
}
