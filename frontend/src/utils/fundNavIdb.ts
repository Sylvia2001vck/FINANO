/**
 * 浏览器侧净值区间缓存（IndexedDB），回访同一基金/区间时秒开，避免重复打后端。
 * 与后端热 TTL（默认约 3 分钟）量级对齐；陈旧条目仍可读，由调用方决定何时刷新。
 */

const DB_NAME = "finano-fund-nav";
const STORE = "lsjz_range";
const DB_VER = 1;
/** 与后端 fund_lsjz_hot_ttl_sec 默认 180s 对齐 */
export const LSJZ_IDB_MAX_AGE_MS = 180_000;

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VER);
    req.onerror = () => reject(req.error ?? new Error("indexedDB open failed"));
    req.onsuccess = () => resolve(req.result);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE);
      }
    };
  });
  return dbPromise;
}

export function lsjzCacheKey(fundCode: string, startDate: string, endDate: string): string {
  return `${fundCode.trim()}|${startDate}|${endDate}`;
}

export async function readLsjzFromIdb(key: string): Promise<{ savedAt: number; payload: unknown } | null> {
  if (typeof indexedDB === "undefined") return null;
  try {
    const db = await openDb();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).get(key);
      req.onerror = () => reject(req.error);
      req.onsuccess = () => {
        const v = req.result as { savedAt: number; payload: unknown } | undefined;
        resolve(v ?? null);
      };
    });
  } catch {
    return null;
  }
}

export async function writeLsjzToIdb(key: string, payload: unknown): Promise<void> {
  if (typeof indexedDB === "undefined") return;
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.objectStore(STORE).put({ savedAt: Date.now(), payload }, key);
    });
  } catch {
    /* 缓存失败不影响主流程 */
  }
}
