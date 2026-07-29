import { useEffect, useRef, type MutableRefObject } from "react";

import type { Timeframe } from "../../../services/market";
import type { MarketSocketManager, MarketSocketStatus } from "../../../services/marketSocket";

interface PwaResumeOptions {
  symbol: string;
  timeframe: Timeframe;
  socketManagerRef: MutableRefObject<MarketSocketManager | null>;
  resync: () => void | Promise<void>;
  setAppVisible: (visible: boolean) => void;
  setResumeGraceUntil: (value: number | ((current: number) => number)) => void;
  setSocketStatus: (status: MarketSocketStatus) => void;
  setStreamConnected: (connected: boolean) => void;
}

/** Restores a suspended PWA without requiring a full app restart. */
export function usePwaResume({
  symbol,
  timeframe,
  socketManagerRef,
  resync,
  setAppVisible,
  setResumeGraceUntil,
  setSocketStatus,
  setStreamConnected,
}: PwaResumeOptions): void {
  const lastResumeAtRef = useRef(0);
  const resumeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    function resumeAndResync() {
      if (document.visibilityState === "hidden") {
        setAppVisible(false);
        return;
      }

      const now = Date.now();
      setAppVisible(true);
      const graceUntil = now + 2500;
      setResumeGraceUntil(graceUntil);
      window.setTimeout(() => {
        setResumeGraceUntil((current) => (current === graceUntil ? 0 : current));
      }, 2600);

      if (now - lastResumeAtRef.current < 400) return;
      lastResumeAtRef.current = now;
      if (resumeTimerRef.current !== null) window.clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = window.setTimeout(() => {
        resumeTimerRef.current = null;
        socketManagerRef.current?.resume(symbol, timeframe);
        socketManagerRef.current?.ensureFresh("resume");
        void resync();
      }, 350);
    }

    function handleOffline() {
      socketManagerRef.current?.markOffline();
      setSocketStatus("disconnected");
      setStreamConnected(false);
    }

    document.addEventListener("visibilitychange", resumeAndResync);
    window.addEventListener("focus", resumeAndResync);
    window.addEventListener("online", resumeAndResync);
    window.addEventListener("pageshow", resumeAndResync);
    window.addEventListener("offline", handleOffline);
    return () => {
      document.removeEventListener("visibilitychange", resumeAndResync);
      window.removeEventListener("focus", resumeAndResync);
      window.removeEventListener("online", resumeAndResync);
      window.removeEventListener("pageshow", resumeAndResync);
      window.removeEventListener("offline", handleOffline);
      if (resumeTimerRef.current !== null) {
        window.clearTimeout(resumeTimerRef.current);
        resumeTimerRef.current = null;
      }
    };
  }, [resync, setAppVisible, setResumeGraceUntil, setSocketStatus, setStreamConnected, socketManagerRef, symbol, timeframe]);
}
