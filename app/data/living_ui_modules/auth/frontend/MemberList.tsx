/** MemberList — who belongs to a resource (memberships collection). */
import { useCallback, useEffect, useState } from 'react'
import { pb } from '@/lib/pb'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useAuth } from './AuthProvider'

interface Member {
  id: string
  role: string
  userId: string
  name: string
  email: string
}

export function MemberList({
  resourceType,
  resourceId,
}: {
  resourceType: string
  resourceId: string
}) {
  const { user, isAdmin } = useAuth()
  const [members, setMembers] = useState<Member[]>([])
  const [myRole, setMyRole] = useState('')

  const load = useCallback(async () => {
    const records = await pb.collection('memberships').getFullList({
      filter: pb.filter(
        'resourceType = {:rt} && resourceId = {:rid}',
        { rt: resourceType, rid: resourceId },
      ),
      expand: 'user',
    })
    const mapped = records.map((r) => ({
      id: r.id,
      role: String(r.role ?? 'member'),
      userId: String(r.user ?? ''),
      name: String(r.expand?.user?.name ?? ''),
      email: String(r.expand?.user?.email ?? ''),
    }))
    setMembers(mapped)
    setMyRole(mapped.find((m) => m.userId === user?.id)?.role ?? '')
  }, [resourceType, resourceId, user?.id])

  useEffect(() => {
    void load()
  }, [load])

  const canRemove = isAdmin || myRole === 'owner' || myRole === 'admin'

  const remove = async (membershipId: string) => {
    await pb.collection('memberships').delete(membershipId)
    void load()
  }

  return (
    <ul className="space-y-2">
      {members.map((m) => (
        <li
          key={m.id}
          className="flex items-center justify-between rounded-md border p-2"
        >
          <div className="flex flex-col">
            <span className="text-sm">{m.name || m.email}</span>
            <span className="text-xs text-muted-foreground">{m.email}</span>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{m.role}</Badge>
            {canRemove && m.role !== 'owner' && m.userId !== user?.id && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void remove(m.id)}
              >
                Remove
              </Button>
            )}
          </div>
        </li>
      ))}
      {members.length === 0 && (
        <li className="text-sm text-muted-foreground">No members yet.</li>
      )}
    </ul>
  )
}
