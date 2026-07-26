/**
 * Auth hook (spec B4, multi-user mode) — thin wrapper over PB's users auth.
 * State derives from pb.authStore; login/register/logout go through the
 * client seam so errors surface consistently.
 */
import { useCallback, useEffect, useState } from 'react';
import { getPbClient } from './client.ts';

export interface AuthState {
  userId: string | null;
  email: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export function useAuth(): AuthState {
  const client = getPbClient();
  const [userId, setUserId] = useState<string | null>(client.pb.authStore.record?.id ?? null);
  // A persisted token can outlive the record it points at: PocketBase apps
  // are served on recycled loopback ports, so localStorage may hold a token
  // minted by a DIFFERENT app (or by this one before its data was reset).
  // The store would look "signed in" while every write fails server-side
  // with `create rule failure`. Validate once on mount and clear if stale.
  useEffect(() => {
    if (client.pb.authStore.record === null) return;
    let cancelled = false;
    void client.pb
      .collection('users')
      .authRefresh()
      .catch(() => {
        if (!cancelled) client.pb.authStore.clear();
      });
    return () => {
      cancelled = true;
    };
  }, [client]);
  const [email, setEmail] = useState<string | null>(
    (client.pb.authStore.record?.['email'] as string | undefined) ?? null,
  );

  useEffect(() => {
    return client.pb.authStore.onChange(() => {
      setUserId(client.pb.authStore.record?.id ?? null);
      setEmail((client.pb.authStore.record?.['email'] as string | undefined) ?? null);
    });
  }, [client]);

  const login = useCallback(
    async (loginEmail: string, password: string): Promise<void> => {
      await client.call((pb) => pb.collection('users').authWithPassword(loginEmail, password));
    },
    [client],
  );

  const register = useCallback(
    async (registerEmail: string, password: string): Promise<void> => {
      await client.call((pb) =>
        pb.collection('users').create({ email: registerEmail, password, passwordConfirm: password }),
      );
      await login(registerEmail, password);
    },
    [client, login],
  );

  const logout = useCallback((): void => {
    client.pb.authStore.clear();
  }, [client]);

  return { userId, email, login, register, logout };
}
