/**
 * LoginGate (spec B4 multi-user): renders children only when authenticated;
 * otherwise a minimal email/password login/register form. The shell's toast
 * handler surfaces auth errors — no custom error plumbing here.
 */
import { useState, type FormEvent, type ReactNode } from 'react';
import { useAuth } from '../pb/auth.ts';
import { Button } from './Button.tsx';
import { Card, CardBody, CardHeader } from './Card.tsx';
import { Input } from './Input.tsx';

export function LoginGate({ children }: { children: ReactNode }): React.JSX.Element {
  const { userId, login, register } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  if (userId !== null) return <>{children}</>;

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setBusy(true);
    try {
      if (mode === 'login') await login(email, password);
      else await register(email, password);
    } catch {
      /* surfaced by shell toast */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader title={mode === 'login' ? 'Sign in' : 'Create account'} />
        <CardBody>
          <form className="flex flex-col gap-3" onSubmit={(e) => void submit(e)}>
            <Input
              label="Email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Input
              label="Password"
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button type="submit" loading={busy} className="mt-1">
              {mode === 'login' ? 'Sign in' : 'Register'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
            >
              {mode === 'login' ? 'No account? Register' : 'Have an account? Sign in'}
            </Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
