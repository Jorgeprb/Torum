import type { ZoneOverlay } from "../chartTypes";

interface NewsZoneOverlayProps {
  overlays: ZoneOverlay[];
}

export function NewsZoneOverlay({ overlays }: NewsZoneOverlayProps) {
  return (
    <div className="news-zone-layer" aria-hidden="true">
      {overlays.map((overlay) => (
        <div
          className={
            overlay.zone.blocks_trading
              ? "news-zone-overlay news-zone-overlay--blocking"
              : "news-zone-overlay"
          }
          key={overlay.id}
          style={{ left: overlay.left, width: overlay.width }}
          title={overlay.zone.reason}
        >
          <span className="news-zone-line news-zone-line--start" />
          <span className="news-zone-line news-zone-line--end" />
        </div>
      ))}
    </div>
  );
}
