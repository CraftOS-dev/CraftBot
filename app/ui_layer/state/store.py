"""Reactive state store with reducer pattern."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional

from app.ui_layer.state.ui_state import UIState, AgentStateType, ActionItemState


# Type alias for state change listeners
StateListener = Callable[[UIState, UIState], None]


class UIStateStore:
    """
    Reactive state store with reducer pattern.

    State changes are made through dispatching actions, which are processed
    by reducers. Listeners are notified of state changes for reactive updates.

    Example:
        store = UIStateStore()

        # Subscribe to state changes
        def on_change(old_state, new_state):
            print(f"Agent state: {new_state.agent_state}")

        unsubscribe = store.subscribe(on_change)

        # Dispatch state change
        store.dispatch("SET_AGENT_STATE", "working")

        # Get current state
        current = store.state
    """

    def __init__(self) -> None:
        """Initialize the state store with default state."""
        self._state = UIState()
        self._listeners: List[StateListener] = []
        self._reducers: Dict[str, Callable[[UIState, Any], UIState]] = {}
        self._register_default_reducers()

    @property
    def state(self) -> UIState:
        """Get the current state (read-only reference)."""
        return self._state

    def subscribe(self, listener: StateListener) -> Callable[[], None]:
        """
        Subscribe to state changes.

        Args:
            listener: Callback function(old_state, new_state) called on changes

        Returns:
            Unsubscribe function that removes the listener
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def dispatch(self, action_type: str, payload: Any = None) -> None:
        """
        Dispatch an action to update state.

        Args:
            action_type: The type of action (e.g., "SET_AGENT_STATE")
            payload: Data for the action
        """
        reducer = self._reducers.get(action_type)
        if not reducer:
            return

        old_state = self._state
        # Create a deep copy to ensure immutability
        new_state = reducer(deepcopy(self._state), payload)
        self._state = new_state

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(old_state, new_state)
            except Exception:
                # Don't let listener errors break the store
                pass

    def register_reducer(
        self,
        action_type: str,
        reducer: Callable[[UIState, Any], UIState],
    ) -> None:
        """
        Register a reducer for an action type.

        Args:
            action_type: The action type this reducer handles
            reducer: Function that takes (state, payload) and returns new state
        """
        self._reducers[action_type] = reducer

    def reset(self) -> None:
        """Reset state to default values."""
        self.dispatch("RESET_STATE", None)

    def _register_default_reducers(self) -> None:
        """Register all built-in reducers."""

        def set_agent_state(state: UIState, agent_state: str) -> UIState:
            state.agent_state = AgentStateType(agent_state)
            state.status_message = _generate_status_message(state)
            return state

        def set_gui_mode(state: UIState, gui_mode: bool) -> UIState:
            state.gui_mode = gui_mode
            return state

        def add_action_item(state: UIState, item_data: Dict) -> UIState:
            item = ActionItemState(
                id=item_data["id"],
                display_name=item_data["display_name"],
                item_type=item_data["item_type"],
                status=item_data.get("status", "running"),
                task_id=item_data.get("task_id"),
                created_at=item_data.get("created_at", 0.0),
            )
            state.action_items[item.id] = item
            if item.id not in state.action_order:
                state.action_order.append(item.id)
            return state

        def update_action_item(state: UIState, data: Dict) -> UIState:
            item_id = data["id"]
            if item_id in state.action_items:
                item = state.action_items[item_id]
                if "status" in data:
                    item.status = data["status"]
                if "display_name" in data:
                    item.display_name = data["display_name"]
            return state

        def remove_action_item(state: UIState, item_id: str) -> UIState:
            state.action_items.pop(item_id, None)
            if item_id in state.action_order:
                state.action_order.remove(item_id)
            return state

        def clear_action_items(state: UIState, _: Any) -> UIState:
            state.action_items.clear()
            state.action_order.clear()
            state.selected_task_id = None
            return state

        def set_current_task(state: UIState, data: Optional[Dict]) -> UIState:
            if data is None:
                state.current_task_id = None
                state.current_task_name = None
            else:
                state.current_task_id = data.get("task_id")
                state.current_task_name = data.get("task_name")
            state.status_message = _generate_status_message(state)
            return state

        def select_task(state: UIState, task_id: Optional[str]) -> UIState:
            state.selected_task_id = task_id
            return state

        def show_menu(state: UIState, show: bool) -> UIState:
            state.show_menu = show
            if show:
                state.show_settings = False
            return state

        def show_settings(state: UIState, show: bool) -> UIState:
            state.show_settings = show
            if show:
                state.show_menu = False
            return state

        def set_settings_tab(state: UIState, tab: str) -> UIState:
            state.settings_tab = tab
            return state

        def set_provider(state: UIState, provider: str) -> UIState:
            state.current_provider = provider
            return state

        def mark_event_seen(state: UIState, key: tuple) -> UIState:
            state.seen_event_keys.add(key)
            return state

        def add_tracked_session(state: UIState, session_id: str) -> UIState:
            state.tracked_sessions.add(session_id)
            return state

        def remove_tracked_session(state: UIState, session_id: str) -> UIState:
            state.tracked_sessions.discard(session_id)
            return state

        def update_loading_frame(state: UIState, _: Any) -> UIState:
            state.loading_frame_index = (state.loading_frame_index + 1) % 10
            return state

        def set_status_message(state: UIState, message: str) -> UIState:
            state.status_message = message
            return state

        def reset_state(state: UIState, _: Any) -> UIState:
            return UIState()

        # Register all reducers
        self._reducers = {
            "SET_AGENT_STATE": set_agent_state,
            "SET_GUI_MODE": set_gui_mode,
            "ADD_ACTION_ITEM": add_action_item,
            "UPDATE_ACTION_ITEM": update_action_item,
            "REMOVE_ACTION_ITEM": remove_action_item,
            "CLEAR_ACTION_ITEMS": clear_action_items,
            "SET_CURRENT_TASK": set_current_task,
            "SELECT_TASK": select_task,
            "SHOW_MENU": show_menu,
            "SHOW_SETTINGS": show_settings,
            "SET_SETTINGS_TAB": set_settings_tab,
            "SET_PROVIDER": set_provider,
            "MARK_EVENT_SEEN": mark_event_seen,
            "ADD_TRACKED_SESSION": add_tracked_session,
            "REMOVE_TRACKED_SESSION": remove_tracked_session,
            "UPDATE_LOADING_FRAME": update_loading_frame,
            "SET_STATUS_MESSAGE": set_status_message,
            "RESET_STATE": reset_state,
        }


def _generate_status_message(state: UIState) -> str:
    """Generate status message based on current state."""
    if state.agent_state == AgentStateType.IDLE:
        return "Agent is idle"
    elif state.agent_state == AgentStateType.WORKING:
        if state.current_task_name:
            return f"Working on: {state.current_task_name}"
        return "Agent is working..."
    elif state.agent_state == AgentStateType.WAITING_FOR_USER:
        return "Waiting for your response"
    elif state.agent_state == AgentStateType.TASK_COMPLETED:
        return "Task completed"
    return "Agent is idle"
