import { format } from "date-fns"
import { Calendar as CalendarIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"

/**
 * The standard shadcn date-picker composition (Popover + Calendar), shipped
 * as a component since there is no registry item for it. Props are
 * accepted in both common idioms:
 *
 *   <DatePicker date={d} onSelect={setD} />
 *   <DatePicker value={d} onChange={setD} placeholder="Due date" />
 */
export interface DatePickerProps {
  date?: Date | undefined
  value?: Date | undefined
  onSelect?: (date: Date | undefined) => void
  onChange?: (date: Date | undefined) => void
  placeholder?: string
  disabled?: boolean
  className?: string
}

export function DatePicker({
  date,
  value,
  onSelect,
  onChange,
  placeholder = "Pick a date",
  disabled,
  className,
}: DatePickerProps) {
  const selected = date ?? value
  const handle = (d: Date | undefined) => {
    onSelect?.(d)
    onChange?.(d)
  }
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          disabled={disabled}
          className={cn(
            "w-full justify-start text-left font-normal",
            !selected && "text-muted-foreground",
            className
          )}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {selected ? format(selected, "PPP") : <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar mode="single" selected={selected} onSelect={handle} />
      </PopoverContent>
    </Popover>
  )
}
