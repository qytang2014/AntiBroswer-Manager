import { useCallback, useEffect, useState } from "react";
import { api, type SystemProxyStatus } from "../lib/api";

let cachedStatus: { timestamp: number; data: SystemProxyStatus } | null = null;
const CACHE_TTL_MS = 30_000;

export function _resetSystemProxyStatusCache() {
  cachedStatus = null;
}

export function useSystemProxyStatus(autoFetch = true) {
  const [status, setStatus] = useState<SystemProxyStatus | null>(() => {
    if (cachedStatus && Date.now() - cachedStatus.timestamp < CACHE_TTL_MS) {
      return cachedStatus.data;
    }
    return null;
  });
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async (force = true) => {
    setLoading(true);
    try {
      // Ensure smooth visual duration (min 400ms) so user sees the refresh spinner clearly
      const [data] = await Promise.all([
        api.getSystemProxyStatus(force),
        new Promise((resolve) => setTimeout(resolve, 400)),
      ]);
      cachedStatus = { timestamp: Date.now(), data };
      setStatus(data);
      return data;
    } catch (err) {
      console.error("Failed to fetch system proxy status", err);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (autoFetch) {
      if (!cachedStatus || Date.now() - cachedStatus.timestamp >= CACHE_TTL_MS) {
        refresh();
      } else if (!status) {
        setStatus(cachedStatus.data);
      }
    }
  }, [autoFetch, refresh, status]);

  return { status, loading, refresh };
}
