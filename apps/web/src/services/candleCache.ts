import type { Candle, Timeframe } from "./market";

const dbName = "torum-candle-cache";
const dbVersion = 1;
const storeName = "candles";

interface CandleCacheRecord {
  key: string;
  candles: Candle[];
  updatedAt: number;
}

let dbPromise: Promise<IDBDatabase | null> | null = null;
const removedMockDateRanges = [
  {
    symbols: new Set(["XAUUSD", "XAUEUR"]),
    from: Date.UTC(2026, 3, 24) / 1000,
    to: Date.UTC(2026, 3, 27) / 1000
  }
];

export function candleStorageKey(symbol: string, timeframe: Timeframe): string {
  return `${symbol.toUpperCase()}:${timeframe}`;
}

function isFinitePrice(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

function isSyntheticDxyCandle(candle: Candle, timeframe: Timeframe): boolean {
  if (timeframe !== "D1" || candle.timeframe !== "D1") {
    return false;
  }

  if (candle.source !== "synthetic_dxy") {
    return false;
  }

  return [candle.open, candle.high, candle.low, candle.close].every((value) => isFinitePrice(value) && value < 200);
}

export function sanitizeCandlesForCache(symbol: string, timeframe: Timeframe, candles: Candle[]): Candle[] {
  const normalizedSymbol = symbol.toUpperCase();
  const withoutRemovedMockDates = candles.filter(
    (candle) =>
      !removedMockDateRanges.some(
        (range) => range.symbols.has(normalizedSymbol) && candle.time >= range.from && candle.time < range.to
      )
  );

  if (normalizedSymbol !== "DXY") {
    return withoutRemovedMockDates;
  }

  return withoutRemovedMockDates.filter((candle) => isSyntheticDxyCandle(candle, timeframe));
}

function openCandleDb(): Promise<IDBDatabase | null> {
  if (typeof window === "undefined" || !("indexedDB" in window)) {
    return Promise.resolve(null);
  }

  if (dbPromise) {
    return dbPromise;
  }

  dbPromise = new Promise((resolve) => {
    let request: IDBOpenDBRequest;
    try {
      request = window.indexedDB.open(dbName, dbVersion);
    } catch {
      resolve(null);
      return;
    }

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(storeName)) {
        db.createObjectStore(storeName, { keyPath: "key" });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });

  return dbPromise;
}

export async function readPersistedCandles(symbol: string, timeframe: Timeframe): Promise<Candle[] | null> {
  const db = await openCandleDb();
  if (!db) {
    return null;
  }

  return new Promise((resolve) => {
    const transaction = db.transaction(storeName, "readonly");
    const request = transaction.objectStore(storeName).get(candleStorageKey(symbol, timeframe));

    request.onsuccess = () => {
      const record = request.result as CandleCacheRecord | undefined;
      const candles = record?.candles?.length ? sanitizeCandlesForCache(symbol, timeframe, record.candles) : [];
      if (record?.candles?.length && candles.length !== record.candles.length) {
        void writePersistedCandles(symbol, timeframe, candles);
      }
      resolve(candles.length ? candles : null);
    };
    request.onerror = () => resolve(null);
  });
}

export async function writePersistedCandles(symbol: string, timeframe: Timeframe, candles: Candle[]): Promise<void> {
  const db = await openCandleDb();
  if (!db) {
    return;
  }

  const cleanCandles = sanitizeCandlesForCache(symbol, timeframe, candles);

  await new Promise<void>((resolve) => {
    const transaction = db.transaction(storeName, "readwrite");
    const store = transaction.objectStore(storeName);
    if (candles.length > 0 && cleanCandles.length === 0) {
      const request = store.delete(candleStorageKey(symbol, timeframe));
      request.onsuccess = () => resolve();
      request.onerror = () => resolve();
      transaction.onabort = () => resolve();
      return;
    }

    const record: CandleCacheRecord = {
      key: candleStorageKey(symbol, timeframe),
      candles: cleanCandles,
      updatedAt: Date.now()
    };
    const request = store.put(record);

    request.onsuccess = () => resolve();
    request.onerror = () => resolve();
    transaction.onabort = () => resolve();
  });
}
