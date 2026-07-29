import { useEffect, useRef, type MutableRefObject } from "react";
import { type IPriceLine, type ISeriesApi, LineStyle } from "lightweight-charts";

interface BidAskPriceLinesOptions {
  seriesRef: MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  symbol: string;
  bidPrice: number | null;
  askPrice: number | null;
  showBidLine: boolean;
  showAskLine: boolean;
}

/** Owns BID/ASK independently from candles, overlays and timeframe resets. */
export function useBidAskPriceLines({
  seriesRef,
  symbol,
  bidPrice,
  askPrice,
  showBidLine,
  showAskLine,
}: BidAskPriceLinesOptions): void {
  const bidLineRef = useRef<IPriceLine | null>(null);
  const askLineRef = useRef<IPriceLine | null>(null);
  const previousSymbolRef = useRef(symbol);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    const removeBid = () => {
      if (bidLineRef.current) series.removePriceLine(bidLineRef.current);
      bidLineRef.current = null;
    };
    const removeAsk = () => {
      if (askLineRef.current) series.removePriceLine(askLineRef.current);
      askLineRef.current = null;
    };

    if (previousSymbolRef.current !== symbol) {
      removeBid();
      removeAsk();
      previousSymbolRef.current = symbol;
    }

    if (!showBidLine || typeof bidPrice !== "number" || !Number.isFinite(bidPrice)) {
      removeBid();
    } else if (bidLineRef.current) {
      bidLineRef.current.applyOptions({ price: bidPrice });
    } else {
      bidLineRef.current = series.createPriceLine({
        price: bidPrice,
        color: "#2be0d0",
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "BID",
      });
    }

    if (!showAskLine || typeof askPrice !== "number" || !Number.isFinite(askPrice)) {
      removeAsk();
    } else if (askLineRef.current) {
      askLineRef.current.applyOptions({ price: askPrice });
    } else {
      askLineRef.current = series.createPriceLine({
        price: askPrice,
        color: "#f45d5d",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "ASK",
      });
    }
  }, [askPrice, bidPrice, seriesRef, showAskLine, showBidLine, symbol]);

  useEffect(() => () => {
    const series = seriesRef.current;
    if (series && bidLineRef.current) series.removePriceLine(bidLineRef.current);
    if (series && askLineRef.current) series.removePriceLine(askLineRef.current);
    bidLineRef.current = null;
    askLineRef.current = null;
  }, [seriesRef]);
}
