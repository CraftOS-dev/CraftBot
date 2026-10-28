/** Renders rows of the dataRows model; rows are expected to be fitted already. */
import { Text } from 'ink'
import type { Row } from './dataRows'

export function RowView({ row }: { row: Row }) {
  if (row.length === 0) return <Text> </Text>
  return (
    <Text wrap="truncate">
      {row.map((s, i) => (
        <Text key={i} color={s.color} bold={s.bold} inverse={s.inverse}>
          {s.text}
        </Text>
      ))}
    </Text>
  )
}
