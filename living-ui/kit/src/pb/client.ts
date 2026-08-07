/**
 * PB client wrapper — the single seam for all network access (spec K2/K7).
 *
 * Resolution order for the backend URL:
 *   1. VITE_PB_URL (dev mode: Vite dev server proxies nothing; PB runs separately)
 *   2. same-origin (production: PocketBase serves the built app from pb_public)
 */
import PocketBase, { ClientResponseError } from 'pocketbase';

export type PbErrorHandler = (error: NormalizedPbError) => void;

export interface NormalizedPbError {
  status: number;
  message: string;
  isAbort: boolean;
  raw: unknown;
}

function normalize(err: unknown): NormalizedPbError {
  if (err instanceof ClientResponseError) {
    return {
      status: err.status,
      message: err.response?.['message'] ?? err.message,
      isAbort: err.isAbort,
      raw: err,
    };
  }
  return {
    status: 0,
    message: err instanceof Error ? err.message : String(err),
    isAbort: false,
    raw: err,
  };
}

/** Owns the PocketBase instance and error fan-out. One per app. */
export class PbClient {
  readonly pb: PocketBase;
  private handlers: PbErrorHandler[] = [];

  constructor(baseUrl?: string) {
    const envUrl =
      typeof import.meta !== 'undefined'
        ? (import.meta as unknown as { env?: Record<string, string> }).env?.['VITE_PB_URL']
        : undefined;
    this.pb = new PocketBase(baseUrl ?? envUrl ?? window.location.origin);
  }

  onError(handler: PbErrorHandler): () => void {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler);
    };
  }

  /** Run a PB call; normalized errors reach every onError subscriber unless silenced. */
  async call<T>(fn: (pb: PocketBase) => Promise<T>, opts?: { silent?: boolean }): Promise<T> {
    try {
      return await fn(this.pb);
    } catch (err) {
      const normalized = normalize(err);
      if (!normalized.isAbort && opts?.silent !== true) {
        for (const handler of this.handlers) handler(normalized);
      }
      throw normalized;
    }
  }
}

let singleton: PbClient | null = null;

/** App-wide client accessor. Shell creates it; everything else consumes it. */
export function getPbClient(): PbClient {
  if (singleton === null) singleton = new PbClient();
  return singleton;
}

export function setPbClient(client: PbClient): void {
  singleton = client;
}
