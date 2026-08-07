/**
 * Realtime data hooks — Living UIs are living by default (spec K2).
 * Strategy: full fetch + realtime subscription; events trigger a debounced refetch
 * (simple, always-consistent; optimize per-event later if ever needed).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { RecordModel, UnsubscribeFunc } from 'pocketbase';
import { getPbClient } from './client.ts';

export interface CollectionQuery {
  filter?: string;
  sort?: string;
  expand?: string;
}

export interface CollectionState<T> {
  records: T[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useCollection<T extends RecordModel>(
  collection: string,
  query: CollectionQuery = {},
): CollectionState<T> {
  const [records, setRecords] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { filter, sort, expand } = query;

  const fetchAll = useCallback(async () => {
    const client = getPbClient();
    try {
      const options: Record<string, string> = {};
      if (filter !== undefined) options['filter'] = filter;
      if (sort !== undefined) options['sort'] = sort;
      if (expand !== undefined) options['expand'] = expand;
      const list = await client.call((pb) => pb.collection(collection).getFullList<T>(options));
      setRecords(list);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [collection, filter, sort, expand]);

  const scheduleRefetch = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => void fetchAll(), 120);
  }, [fetchAll]);

  useEffect(() => {
    let unsubscribe: UnsubscribeFunc | null = null;
    let cancelled = false;

    void fetchAll();
    void getPbClient()
      .call((pb) => pb.collection(collection).subscribe('*', scheduleRefetch), { silent: true })
      .then((fn) => {
        if (cancelled) void fn();
        else unsubscribe = fn;
      })
      .catch(() => {
        /* realtime unavailable — data still loads, just not live */
      });

    return () => {
      cancelled = true;
      if (timer.current !== null) clearTimeout(timer.current);
      if (unsubscribe !== null) void unsubscribe();
    };
  }, [collection, fetchAll, scheduleRefetch]);

  return { records, loading, error, refresh: () => void fetchAll() };
}

export interface RecordState<T> {
  record: T | null;
  loading: boolean;
  error: string | null;
}

export function useRecord<T extends RecordModel>(collection: string, id: string | null): RecordState<T> {
  const [record, setRecord] = useState<T | null>(null);
  const [loading, setLoading] = useState(id !== null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id === null) {
      setRecord(null);
      setLoading(false);
      return;
    }
    let unsubscribe: UnsubscribeFunc | null = null;
    let cancelled = false;
    setLoading(true);

    const client = getPbClient();
    void client
      .call((pb) => pb.collection(collection).getOne<T>(id))
      .then((r) => {
        if (!cancelled) setRecord(r);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load record');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    void client
      .call(
        (pb) =>
          pb.collection(collection).subscribe<T>(id, (e) => {
            setRecord(e.action === 'delete' ? null : e.record);
          }),
        { silent: true },
      )
      .then((fn) => {
        if (cancelled) void fn();
        else unsubscribe = fn;
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      if (unsubscribe !== null) void unsubscribe();
    };
  }, [collection, id]);

  return { record, loading, error };
}
