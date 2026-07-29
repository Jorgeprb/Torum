import type { Candle, Timeframe } from "./market";

const dbName = "torum-candle-cache";
const dbVersion = 2;
const legacyStoreName = "candles";
const chunkStoreName = "candleChunks";
const chunkIndexName = "marketKey";
const candlesPerChunk = 256;

interface LegacyCandleCacheRecord {
  key: string;
  candles: Candle[];
  updatedAt: number;
}

interface CandleChunkRecord {
  id: string;
  marketKey: string;
  startTime: number;
  candles: Candle[];
  fingerprint: string;
  updatedAt: number;
}

let dbPromise: Promise<IDBDatabase | null> | null = null;
const knownChunkFingerprints = new Map<string, string>();
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

function timeframeSeconds(timeframe: Timeframe): number {
  const values: Record<Timeframe, number> = {
    M1: 60,
    M5: 300,
    H1: 3600,
    H2: 7200,
    H3: 10800,
    H4: 14400,
    D1: 86400,
    W1: 604800
  };
  return values[timeframe] ?? 300;
}

function isFinitePrice(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

function isSyntheticDxyCandle(candle: Candle, timeframe: Timeframe): boolean {
  if (timeframe !== "D1" || candle.timeframe !== "D1") return false;
  if (candle.source !== "synthetic_dxy") return false;
  return [candle.open, candle.high, candle.low, candle.close].every((value) => isFinitePrice(value) && value < 200);
}

export function sanitizeCandlesForCache(symbol: string, timeframe: Timeframe, candles: Candle[]): Candle[] {
  const normalizedSymbol = symbol.toUpperCase();
  const byTime = new Map<number, Candle>();
  for (const candle of candles) {
    if (!Number.isFinite(candle.time)) continue;
    if (
      removedMockDateRanges.some(
        (range) => range.symbols.has(normalizedSymbol) && candle.time >= range.from && candle.time < range.to
      )
    ) continue;
    if (normalizedSymbol === "DXY" && !isSyntheticDxyCandle(candle, timeframe)) continue;
    byTime.set(candle.time, candle);
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

function openCandleDb(): Promise<IDBDatabase | null> {
  if (typeof window === "undefined" || !("indexedDB" in window)) return Promise.resolve(null);
  if (dbPromise) return dbPromise;

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
      if (!db.objectStoreNames.contains(legacyStoreName)) {
        db.createObjectStore(legacyStoreName, { keyPath: "key" });
      }
      if (!db.objectStoreNames.contains(chunkStoreName)) {
        const store = db.createObjectStore(chunkStoreName, { keyPath: "id" });
        store.createIndex(chunkIndexName, "marketKey", { unique: false });
      } else {
        const store = request.transaction?.objectStore(chunkStoreName);
        if (store && !store.indexNames.contains(chunkIndexName)) {
          store.createIndex(chunkIndexName, "marketKey", { unique: false });
        }
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
  return dbPromise;
}

function chunkRecords(symbol: string, timeframe: Timeframe, candles: Candle[]): CandleChunkRecord[] {
  const marketKey = candleStorageKey(symbol, timeframe);
  const span = timeframeSeconds(timeframe) * candlesPerChunk;
  const groups = new Map<number, Candle[]>();
  for (const candle of candles) {
    const startTime = Math.floor(candle.time / span) * span;
    const group = groups.get(startTime) ?? [];
    group.push(candle);
    groups.set(startTime, group);
  }
  const now = Date.now();
  return [...groups.entries()].map(([startTime, chunkCandles]) => {
    const sorted = chunkCandles.sort((a, b) => a.time - b.time);
    const fingerprint = sorted
      .map((candle) => `${candle.time}:${candle.open}:${candle.high}:${candle.low}:${candle.close}:${candle.volume ?? ""}`)
      .join("|");
    return {
      id: `${marketKey}:${startTime}`,
      marketKey,
      startTime,
      candles: sorted,
      fingerprint,
      updatedAt: now
    };
  });
}

function readChunks(db: IDBDatabase, marketKey: string): Promise<CandleChunkRecord[]> {
  return new Promise((resolve) => {
    if (!db.objectStoreNames.contains(chunkStoreName)) {
      resolve([]);
      return;
    }
    const transaction = db.transaction(chunkStoreName, "readonly");
    const request = transaction.objectStore(chunkStoreName).index(chunkIndexName).getAll(IDBKeyRange.only(marketKey));
    request.onsuccess = () => resolve((request.result as CandleChunkRecord[] | undefined) ?? []);
    request.onerror = () => resolve([]);
    transaction.onabort = () => resolve([]);
  });
}

function readLegacy(db: IDBDatabase, marketKey: string): Promise<Candle[] | null> {
  return new Promise((resolve) => {
    if (!db.objectStoreNames.contains(legacyStoreName)) {
      resolve(null);
      return;
    }
    const transaction = db.transaction(legacyStoreName, "readonly");
    const request = transaction.objectStore(legacyStoreName).get(marketKey);
    request.onsuccess = () => {
      const record = request.result as LegacyCandleCacheRecord | undefined;
      resolve(record?.candles?.length ? record.candles : null);
    };
    request.onerror = () => resolve(null);
    transaction.onabort = () => resolve(null);
  });
}

export async function readPersistedCandles(symbol: string, timeframe: Timeframe): Promise<Candle[] | null> {
  const db = await openCandleDb();
  if (!db) return null;

  const marketKey = candleStorageKey(symbol, timeframe);
  const chunks = await readChunks(db, marketKey);
  if (chunks.length > 0) {
    for (const chunk of chunks) knownChunkFingerprints.set(chunk.id, chunk.fingerprint);
    const candles = sanitizeCandlesForCache(
      symbol,
      timeframe,
      chunks.sort((a, b) => a.startTime - b.startTime).flatMap((chunk) => chunk.candles)
    );
    return candles.length ? candles : null;
  }

  // One-time migration from the original monolithic record.
  const legacy = await readLegacy(db, marketKey);
  if (!legacy?.length) return null;
  const clean = sanitizeCandlesForCache(symbol, timeframe, legacy);
  await writePersistedCandles(symbol, timeframe, clean);
  return clean.length ? clean : null;
}

export async function writePersistedCandles(symbol: string, timeframe: Timeframe, candles: Candle[]): Promise<void> {
  const db = await openCandleDb();
  if (!db) return;

  const marketKey = candleStorageKey(symbol, timeframe);
  const cleanCandles = sanitizeCandlesForCache(symbol, timeframe, candles);
  const chunks = chunkRecords(symbol, timeframe, cleanCandles);
  const nextIds = new Set(chunks.map((chunk) => chunk.id));

  await new Promise<void>((resolve) => {
    const stores = [chunkStoreName, legacyStoreName].filter((name) => db.objectStoreNames.contains(name));
    const transaction = db.transaction(stores, "readwrite");
    const chunkStore = transaction.objectStore(chunkStoreName);
    const keysRequest = chunkStore.index(chunkIndexName).getAllKeys(IDBKeyRange.only(marketKey));

    keysRequest.onsuccess = () => {
      for (const rawKey of keysRequest.result) {
        const id = String(rawKey);
        if (!nextIds.has(id)) {
          chunkStore.delete(id);
          knownChunkFingerprints.delete(id);
        }
      }
      for (const chunk of chunks) {
        if (knownChunkFingerprints.get(chunk.id) === chunk.fingerprint) continue;
        chunkStore.put(chunk);
        knownChunkFingerprints.set(chunk.id, chunk.fingerprint);
      }
      if (transaction.objectStoreNames.contains(legacyStoreName)) {
        transaction.objectStore(legacyStoreName).delete(marketKey);
      }
    };
    keysRequest.onerror = () => undefined;
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => resolve();
    transaction.onabort = () => resolve();
  });
}
