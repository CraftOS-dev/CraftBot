/**
 * App→agent trigger plane, frontend side (spec TRIGGERS-PLAN).
 *
 * `fireAgentTrigger` inserts a row into the `agent_requests` queue — the
 * in-app guard validates it against triggers.json (declared name, param
 * types, cooldown, hourly cap) — and `useAgentRequest` follows that row so
 * the UI can render "agent working… → done: <result>".
 *
 * Degrades gracefully by design: with no agent attached the row simply stays
 * `pending` — render that honestly ("no agent connected yet"), never spin
 * forever. A rejected fire (cooldown, bad params) resolves the promise with
 * `ok: false` and a human-readable reason; it never throws.
 */
import { useEffect, useState } from 'react';
import type { RecordModel, UnsubscribeFunc } from 'pocketbase';
import { getPbClient } from './client.ts';

export interface AgentRequestRecord extends RecordModel {
  trigger: string;
  params: Record<string, unknown>;
  status: 'pending' | 'claimed' | 'done' | 'rejected';
  fired_by: 'ui' | 'hook' | 'cli';
  claimed_by: string;
  result: string;
  error: string;
}

export interface FireResult {
  ok: boolean;
  /** The queue row id when ok — pass it to useAgentRequest. */
  requestId?: string;
  /** Machine code on refusal (cooldown, undeclared_trigger, …). */
  code?: string;
  message?: string;
}

export async function fireAgentTrigger(
  trigger: string,
  params: Record<string, unknown> = {},
): Promise<FireResult> {
  const client = getPbClient();
  try {
    const record = await client.call((pb) =>
      pb.collection('agent_requests').create<AgentRequestRecord>({
        trigger,
        params,
        status: 'pending',
        fired_by: 'ui',
      }),
    );
    return { ok: true, requestId: record.id };
  } catch (err) {
    const raw = err as {
      status?: number;
      response?: { code?: string; message?: string };
      message?: string;
    };
    return {
      ok: false,
      code: raw.response?.code ?? String(raw.status ?? 'error'),
      message: raw.response?.message ?? raw.message ?? 'fire failed',
    };
  }
}

export interface AgentRequestState {
  request: AgentRequestRecord | null;
  /** Convenience: true while status is pending or claimed. */
  working: boolean;
}

/** Follow one fired request (realtime + initial fetch). Pass null to idle. */
export function useAgentRequest(requestId: string | null): AgentRequestState {
  const [record, setRecord] = useState<AgentRequestRecord | null>(null);

  useEffect(() => {
    if (requestId === null) {
      setRecord(null);
      return;
    }
    const client = getPbClient();
    let cancelled = false;
    let unsubscribe: UnsubscribeFunc | null = null;

    client
      .call((pb) => pb.collection('agent_requests').getOne<AgentRequestRecord>(requestId))
      .then((row) => {
        if (!cancelled) setRecord(row);
      })
      .catch(() => {
        /* row may not be visible yet; realtime will deliver it */
      });
    client
      .call((pb) =>
        pb.collection('agent_requests').subscribe<AgentRequestRecord>(requestId, (e) => {
          if (!cancelled) setRecord(e.record);
        }),
      )
      .then((fn) => {
        unsubscribe = fn;
        if (cancelled) void fn();
      })
      .catch(() => {
        /* realtime unavailable — the initial fetch still rendered state */
      });

    return () => {
      cancelled = true;
      if (unsubscribe !== null) void unsubscribe();
    };
  }, [requestId]);

  return {
    request: record,
    working: record !== null && (record.status === 'pending' || record.status === 'claimed'),
  };
}
