type RateLimitOptions = {
  key: string;
  limit: number;
  windowMs: number;
};

type RateLimitRecord = {
  count: number;
  resetAt: number;
};

type RateLimitStore = Map<string, RateLimitRecord>;

declare global {
  var __aihmRateLimitStore: RateLimitStore | undefined;
}

function getStore() {
  if (!globalThis.__aihmRateLimitStore) {
    globalThis.__aihmRateLimitStore = new Map<string, RateLimitRecord>();
  }

  return globalThis.__aihmRateLimitStore;
}

export function consumeRateLimit({ key, limit, windowMs }: RateLimitOptions) {
  const now = Date.now();
  const store = getStore();

  for (const [entryKey, entry] of store.entries()) {
    if (entry.resetAt <= now) {
      store.delete(entryKey);
    }
  }

  const existing = store.get(key);

  if (!existing || existing.resetAt <= now) {
    store.set(key, {
      count: 1,
      resetAt: now + windowMs,
    });

    return {
      ok: true,
      retryAfterMs: 0,
      remaining: limit - 1,
    };
  }

  if (existing.count >= limit) {
    return {
      ok: false,
      retryAfterMs: Math.max(existing.resetAt - now, 0),
      remaining: 0,
    };
  }

  existing.count += 1;
  store.set(key, existing);

  return {
    ok: true,
    retryAfterMs: 0,
    remaining: Math.max(limit - existing.count, 0),
  };
}