/** UserMenu — header dropdown with the signed-in user and sign-out. */
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from './AuthProvider'

export function UserMenu({ onOpenProfile }: { onOpenProfile?: () => void }) {
  const { user, isAdmin, logout } = useAuth()
  if (!user) return null

  const initials =
    (user.name || user.email)
      .split(/[\s@]+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .join('') || '?'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="rounded-full">
          <Avatar className="h-8 w-8">
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <div className="flex flex-col">
            <span>{user.name || user.email}</span>
            <span className="text-xs font-normal text-muted-foreground">
              {user.email}
              {isAdmin ? ' · admin' : ''}
            </span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {onOpenProfile && (
          <DropdownMenuItem onSelect={onOpenProfile}>Profile</DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={logout}>Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
