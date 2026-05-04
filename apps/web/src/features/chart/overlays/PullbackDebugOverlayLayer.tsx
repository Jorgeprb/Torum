import type { PullbackDebugOverlay } from "../chartTypes";

interface PullbackDebugOverlayProps {
  overlays: PullbackDebugOverlay[];
}

export function PullbackDebugOverlayLayer({ overlays }: PullbackDebugOverlayProps) {
  return (
    <div className="pullback-debug-layer" aria-hidden="true">
      {overlays.map((overlay) => {
        const dx = overlay.x2 - overlay.x1;
        const dy = overlay.y2 - overlay.y1;
        const length = Math.max(2, Math.hypot(dx, dy));
        const angle = Math.atan2(dy, dx);
        return (
          <div
            className="pullback-debug"
            key={`${overlay.debug.swing_high_time}:${overlay.debug.pullback_low_time}`}
          >
            <span
              className="pullback-debug__line"
              style={{
                left: overlay.x1,
                top: overlay.y1,
                width: length,
                transform: `rotate(${angle}rad)`
              }}
            />
            <span
              className="pullback-debug__label"
              style={{ left: overlay.x2 + 6, top: overlay.y2 - 14 }}
            >
              {overlay.debug.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
