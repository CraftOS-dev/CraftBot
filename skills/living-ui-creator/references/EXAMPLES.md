# Living UI Code Examples

Complete code examples for each development phase.

## Backend Model Example

**File: `backend/models.py`**

```python
# Example: Add a Todo model
class Todo(Base):
    __tablename__ = "todos"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    text = Column(String, nullable=False)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "completed": self.completed,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
```

## Backend Routes Example

**File: `backend/routes.py`**

```python
# Example: Add todo routes
@router.get("/todos")
def get_todos(db: Session = Depends(get_db)) -> List[Dict]:
    todos = db.query(Todo).order_by(Todo.created_at).all()
    return [t.to_dict() for t in todos]


@router.post("/todos")
def create_todo(data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict:
    todo = Todo(text=data["text"])
    db.add(todo)
    db.commit()
    return todo.to_dict()


@router.put("/todos/{todo_id}")
def update_todo(
    todo_id: str, data: Dict[str, Any], db: Session = Depends(get_db)
) -> Dict:
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    if "completed" in data:
        todo.completed = data["completed"]
    if "text" in data:
        todo.text = data["text"]
    db.commit()
    return todo.to_dict()


@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: str, db: Session = Depends(get_db)) -> Dict:
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    db.delete(todo)
    db.commit()
    return {"status": "deleted"}
```

## Frontend Types Example

**File: `frontend/types.ts`**

```typescript
export interface Todo {
  id: string
  text: string
  completed: boolean
  createdAt: string
}

export interface AppState {
  initialized: boolean
  loading: boolean
  error: string | null
  todos: Todo[]  // Add your data here
}
```

## React Component Example

**File: `frontend/components/TodoList.tsx`**

```typescript
interface TodoListProps {
  todos: Todo[]
  onToggle: (id: string) => void
  onDelete: (id: string) => void
}

export function TodoList({ todos, onToggle, onDelete }: TodoListProps) {
  return (
    <ul className="todo-list">
      {todos.map(todo => (
        <li key={todo.id} className={todo.completed ? 'completed' : ''}>
          <input
            type="checkbox"
            checked={todo.completed}
            onChange={() => onToggle(todo.id)}
          />
          <span>{todo.text}</span>
          <button onClick={() => onDelete(todo.id)}>Delete</button>
        </li>
      ))}
    </ul>
  )
}
```

## AppController Methods Example

**File: `frontend/AppController.ts`**

```typescript
// Add to AppController class
async fetchTodos(): Promise<void> {
  const response = await fetch(`${this.backendUrl}/todos`)
  const todos = await response.json()
  await this.setState({ todos })
}

async addTodo(text: string): Promise<void> {
  const response = await fetch(`${this.backendUrl}/todos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  })
  const todo = await response.json()
  const todos = [...this.state.todos, todo]
  await this.setState({ todos })
}

async toggleTodo(id: string): Promise<void> {
  const todo = this.state.todos.find(t => t.id === id)
  if (!todo) return

  await fetch(`${this.backendUrl}/todos/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ completed: !todo.completed })
  })

  const todos = this.state.todos.map(t =>
    t.id === id ? { ...t, completed: !t.completed } : t
  )
  await this.setState({ todos })
}
```

## MainView Example

**File: `frontend/components/MainView.tsx`**

```typescript
import { useState, useEffect } from 'react'
import { TodoList } from './TodoList'
import type { AppController } from '../AppController'

export function MainView({ controller }: { controller: AppController }) {
  const [state, setState] = useState(controller.getState())

  useEffect(() => {
    // Subscribe to state changes
    const unsubscribe = controller.subscribe(setState)
    // Fetch initial data
    controller.fetchTodos()
    return unsubscribe
  }, [controller])

  return (
    <main>
      <h1>My Todos</h1>
      <TodoList
        todos={state.todos || []}
        onToggle={(id) => controller.toggleTodo(id)}
        onDelete={(id) => controller.deleteTodo(id)}
      />
    </main>
  )
}
```

## Notify Ready Example

```
living_ui_notify_ready(
  project_id="<PROJECT_ID from task instruction - NOT task session ID>",
  url="http://localhost:<port from manifest.json>",
  port=<port from manifest.json>
)
```

**Example (replace PORT with value from config/manifest.json):**
```
living_ui_notify_ready(
  project_id="b022f7bb",  # From task instruction, NOT session ID
  url="http://localhost:PORT",
  port=PORT
)
```
