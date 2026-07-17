/** InviteModal — create a shareable invite code, or join with one. */
import { useState } from 'react'
import { pb } from '@/lib/pb'
import { ApiService } from '@/services/ApiService'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from './AuthProvider'

function randomCode(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(6)))
    .map((b) => 'abcdefghjkmnpqrstuvwxyz23456789'[b % 31])
    .join('')
}

export function InviteModal({
  resourceType,
  resourceId,
  open,
  onOpenChange,
}: {
  resourceType: string
  resourceId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { user } = useAuth()
  const [createdCode, setCreatedCode] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [status, setStatus] = useState('')

  const createInvite = async () => {
    if (!user) return
    const code = randomCode()
    await pb.collection('invites').create({
      code,
      resourceType,
      resourceId,
      role: 'member',
      createdBy: user.id,
    })
    setCreatedCode(code)
  }

  const acceptInvite = async () => {
    setStatus('')
    try {
      const result = await ApiService.request<{ status: string }>(
        'POST',
        '/custom/invites/accept',
        { code: joinCode.trim() },
      )
      setStatus(
        result.status === 'already-member' ? 'Already a member' : 'Joined!',
      )
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Could not join')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Invite people</DialogTitle>
          <DialogDescription>
            Share a code, or join with one you received.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Create an invite</Label>
            {createdCode ? (
              <p className="rounded-md border p-2 font-mono text-sm">
                {createdCode}
              </p>
            ) : (
              <Button onClick={() => void createInvite()}>
                Generate code
              </Button>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-join-code">Join with a code</Label>
            <div className="flex gap-2">
              <Input
                id="invite-join-code"
                value={joinCode}
                onChange={(e) => setJoinCode(e.target.value)}
                placeholder="e.g. x7k2mp"
              />
              <Button
                variant="secondary"
                disabled={!joinCode.trim()}
                onClick={() => void acceptInvite()}
              >
                Join
              </Button>
            </div>
            {status && (
              <p className="text-sm text-muted-foreground">{status}</p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
