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

export function candleStorageKey(symbol: string, timeframe: Timeframe): string {
  return `${symbol.toUpperCase()}:${timeframe}`;
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
      resolve(record?.candles?.length ? record.candles : null);
    };
    request.onerror = () => resolve(null);
  });
}

export async function writePersistedCandles(symbol: string, timeframe: Timeframe, candles: Candle[]): Promise<void> {
  const db = await openCandleDb();
  if (!db) {
    return;
  }

  await new Promise<void>((resolve) => {
    const transaction = db.transaction(storeName, "readwrite");
    const record: CandleCacheRecord = {
      key: candleStorageKey(symbol, timeframe),
      candles,
      updatedAt: Date.now()
    };
    const request = transaction.objectStore(storeName).put(record);

    request.onsuccess = () => resolve();
    request.onerror = () => resolve();
    transaction.onabort = () => resolve();
  });
}
