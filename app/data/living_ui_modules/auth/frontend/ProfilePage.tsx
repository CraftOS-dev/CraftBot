/** ProfilePage — edit name and change password (PB user record update). */
import { useState, type FormEvent } from 'react'
import { pb } from '@/lib/pb'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from './AuthProvider'

export function ProfilePage({ onClose }: { onClose?: () => void }) {
  const { user } = useAuth()
  const [name, setName] = useState(user?.name ?? '')
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!user) return null

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setMessage('')
    setError('')
    setBusy(true)
    try {
      const changes: Record<string, string> = { name }
      if (newPassword) {
        // PB requires the current password to authorize a password change,
        // and invalidates the session token afterwards — re-authenticate.
        changes.oldPassword = oldPassword
        changes.password = newPassword
        changes.passwordConfirm = newPassword
      }
      await pb.collection('users').update(user.id, changes)
      if (newPassword) {
        await pb
          .collection('users')
          .authWithPassword(user.email, newPassword)
        setOldPassword('')
        setNewPassword('')
      }
      setMessage('Profile updated')
    } catch {
      setError(
        newPassword
          ? 'Update failed — is the current password correct?'
          : 'Update failed',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Profile</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="profile-name">Name</Label>
            <Input
              id="profile-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-old-password">Current password</Label>
            <Input
              id="profile-old-password"
              type="password"
              autoComplete="current-password"
              placeholder="Only to change your password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-new-password">New password</Label>
            <Input
              id="profile-new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </div>
          {message && <p className="text-sm text-muted-foreground">{message}</p>}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Save'}
            </Button>
            {onClose && (
              <Button type="button" variant="ghost" onClick={onClose}>
                Close
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
