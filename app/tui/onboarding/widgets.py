# -*- coding: utf-8 -*-
"""
Textual widgets for the onboarding wizard.
"""

from typing import TYPE_CHECKING, Any, List, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static, ListView, ListItem, Label, Button, Input

from rich.text import Text

if TYPE_CHECKING:
    from app.tui.onboarding.hard_onboarding import TUIHardOnboarding


ONBOARDING_CSS = """
/* Onboarding wizard screen - matches settings-card style */
OnboardingWizardScreen {
    align: center middle;
    background: #000000;
}

#onboarding-container {
    max-width: 100%;
    height: 100%;
    border: none;
    background: #000000;
    padding: 2 3 3 3;
    content-align: center top;
    overflow: auto;
    layout: vertical;
}

#onboarding-header {
    height: auto;
    margin-bottom: 1;
}

#onboarding-title {
    text-style: bold;
    color: #ffffff;
    margin-bottom: 1;
}

#onboarding-progress {
    color: #666666;
}

#step-container {
    height: auto;
    margin-bottom: 1;
    padding: 1 0;
}

#step-title {
    text-style: bold;
    color: #ffffff;
    margin-bottom: 1;
}

#step-description {
    color: #a0a0a0;
    margin-bottom: 1;
}

#step-content {
    height: auto;
    margin: 1 0;
}

/* Option list for selections - matches provider-options style */
.option-list {
    width: 28;
    height: auto;
    max-height: 12;
    margin: 1 0;
    background: transparent;
    border: none;
}

.option-list > ListItem {
    padding: 0 0;
}

.option-list > ListItem.--highlight .option-label {
    background: #ff4f18;
    color: #ffffff;
    text-style: bold;
}

.option-label {
    color: #a0a0a0;
}

.option-desc {
    color: #666666;
    margin-left: 2;
}

/* Text input - matches settings-card Input style */
.step-input {
    width: 100%;
    border: solid #2a2a2a;
    background: #0a0a0a;
    color: #e5e5e5;
}

.step-input:focus {
    border: solid #ff4f18;
}

/* Multi-select list - matches skills-list/mcp-server-list style */
.multi-select-list {
    height: auto;
    max-height: 15;
    margin: 1 0;
    border: solid #2a2a2a;
    background: #0a0a0a;
    padding: 1;
}

.multi-select-row {
    height: 1;
    margin-bottom: 1;
}

.multi-select-toggle {
    width: 3;
    min-width: 3;
    height: 1;
    background: #333333;
    color: #666666;
    border: none;
    margin-right: 1;
}

.multi-select-toggle.-selected {
    color: #00cc00;
}

.multi-select-toggle:hover {
    background: #00cc00;
    color: #000000;
}

.multi-select-label {
    width: 1fr;
    color: #a0a0a0;
}

/* Error message */
#step-error {
    color: #ff4444;
    margin-top: 1;
}

/* Navigation actions - matches settings-actions-list style */
#nav-actions {
    width: 24;
    height: auto;
    margin-top: 1;
    content-align: center middle;
    background: transparent;
    border: none;
}

#nav-actions > ListItem {
    padding: 0 0;
}

#nav-actions > ListItem.--highlight .nav-item {
    background: #ff4f18;
    color: #ffffff;
    text-style: bold;
}

.nav-item {
    color: #a0a0a0;
}

.nav-item.-disabled {
    color: #444444;
}

/* Skip hint */
#skip-hint {
    color: #666666;
    text-style: italic;
    margin-top: 1;
}
"""


class OnboardingWizardScreen(Screen):
    """
    Multi-step wizard screen for hard onboarding.

    Guides user through:
    1. LLM Provider selection
    2. API Key input
    3. Agent name (optional)
    4. MCP server selection (optional)
    5. Skills selection (optional)

    User name is collected during soft onboarding (conversational interview).
    """

    CSS = ONBOARDING_CSS

    def __init__(self, handler: "TUIHardOnboarding"):
        super().__init__()
        self._handler = handler
        self._current_step = 0
        self._multi_select_values: List[str] = []

    def compose(self) -> ComposeResult:
        with Container(id="onboarding-container"):
            with Container(id="onboarding-header"):
                yield Static("Setup", id="onboarding-title")
                yield Static(self._get_progress_text(), id="onboarding-progress")

            with Container(id="step-container"):
                yield Static("", id="step-title")
                yield Static("", id="step-description")
                yield Container(id="step-content")
                yield Static("", id="step-error")

            yield ListView(
                ListItem(Label("next", classes="nav-item"), id="nav-next"),
                ListItem(Label("skip", classes="nav-item"), id="nav-skip"),
                ListItem(Label("back", classes="nav-item"), id="nav-back"),
                id="nav-actions",
            )

            yield Static("", id="skip-hint")

    def on_mount(self) -> None:
        """Initialize the first step when mounted."""
        # Set initial navigation selection
        nav_list = self.query_one("#nav-actions", ListView)
        nav_list.index = 0
        self._show_step(0)

    def _get_progress_text(self) -> str:
        """Get progress indicator text."""
        total = self._handler.get_step_count()
        current = self._current_step + 1
        return f"Step {current} of {total}"

    def _show_step(self, index: int) -> None:
        """Display the step at the given index."""
        self._current_step = index
        step = self._handler.get_step(index)

        # Update progress
        self.query_one("#onboarding-progress", Static).update(self._get_progress_text())

        # Update step title and description
        self.query_one("#step-title", Static).update(step.title)
        self.query_one("#step-description", Static).update(step.description)

        # Clear error
        self.query_one("#step-error", Static).update("")

        # Update navigation items visibility and styling
        self._update_nav_items(index, step.required)

        # Update skip hint
        skip_hint = self.query_one("#skip-hint", Static)
        if not step.required:
            skip_hint.update("This step is optional - you can skip it")
        else:
            skip_hint.update("")

        # Build step content
        content = self.query_one("#step-content", Container)
        content.remove_children()

        options = step.get_options()

        if step.name in ("mcp", "skills"):
            # Multi-select list
            self._multi_select_values = step.get_default()
            self._build_multi_select(content, options)
        elif options:
            # Single-select list
            self._build_option_list(content, options, step.get_default())
        else:
            # Text input
            self._build_text_input(content, step.get_default())

    def _update_nav_items(self, index: int, required: bool) -> None:
        """Update navigation items based on current step."""
        # Update back item - disable on first step
        back_item = self.query_one("#nav-back", ListItem)
        back_label = back_item.query_one(Label)
        if index == 0:
            back_label.add_class("-disabled")
        else:
            back_label.remove_class("-disabled")

        # Update skip item - hide if step is required
        skip_item = self.query_one("#nav-skip", ListItem)
        skip_item.display = not required

        # Set initial selection to "next"
        nav_list = self.query_one("#nav-actions", ListView)
        nav_list.index = 0

    def _build_option_list(self, container: Container, options: list, default: str) -> None:
        """Build a single-select option list."""
        items = []
        highlight_idx = 0
        step = self._handler.get_step(self._current_step)

        for i, opt in enumerate(options):
            label_text = f"  {opt.label}"
            if opt.description:
                label_text += f"  ({opt.description})"

            items.append(ListItem(Label(label_text, classes="option-label"), id=f"opt-{step.name}-{opt.value}"))

            if opt.value == default:
                highlight_idx = i

        list_view = ListView(*items, id=f"option-list-{step.name}", classes="option-list")
        container.mount(list_view)

        # Highlight default after mount
        def set_highlight():
            list_view.index = highlight_idx
        self.call_after_refresh(set_highlight)

    def _build_text_input(self, container: Container, default: str) -> None:
        """Build a text input field."""
        # Check if this is API key step (should be password field)
        step = self._handler.get_step(self._current_step)
        is_password = step.name == "api_key"

        input_widget = Input(
            value=default,
            placeholder="Enter value..." if not is_password else "Enter API key (Ctrl+V to paste)",
            password=False,  # Show API key for clarity during setup
            id=f"step-input-{step.name}",
            classes="step-input"
        )
        container.mount(input_widget)
        self.call_after_refresh(input_widget.focus)

    def _build_multi_select(self, container: Container, options: list) -> None:
        """Build a multi-select list with toggle buttons."""
        step = self._handler.get_step(self._current_step)
        scroll = VerticalScroll(id=f"multi-select-list-{step.name}", classes="multi-select-list")

        for opt in options:
            is_selected = opt.value in self._multi_select_values
            toggle_text = "[+]" if is_selected else "[-]"
            toggle_class = "multi-select-toggle -selected" if is_selected else "multi-select-toggle"

            row = Horizontal(
                Button(toggle_text, id=f"toggle-{opt.value}", classes=toggle_class),
                Static(opt.label, classes="multi-select-label"),
                classes="multi-select-row"
            )
            scroll.compose_add_child(row)

        container.mount(scroll)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses (for multi-select toggles)."""
        button_id = event.button.id

        if button_id and button_id.startswith("toggle-"):
            value = button_id[7:]  # Remove "toggle-" prefix
            self._toggle_multi_select(value, event.button)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list view selection."""
        list_id = event.list_view.id

        # Handle navigation actions
        if list_id == "nav-actions":
            if event.item.id == "nav-next":
                self._go_next()
            elif event.item.id == "nav-skip":
                self._skip_step()
            elif event.item.id == "nav-back":
                # Check if back is enabled (not on first step)
                if self._current_step > 0:
                    self._go_back()

        # Check if it's an option list (IDs are now like "option-list-provider")
        elif list_id and list_id.startswith("option-list-"):
            # Don't auto-advance on selection, wait for next action
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input field."""
        self._go_next()

    def _toggle_multi_select(self, value: str, button: Button) -> None:
        """Toggle a multi-select option."""
        if value in self._multi_select_values:
            self._multi_select_values.remove(value)
            button.label = "[-]"
            button.remove_class("-selected")
        else:
            self._multi_select_values.append(value)
            button.label = "[+]"
            button.add_class("-selected")

    def _get_current_value(self) -> Any:
        """Get the current value from the active step widget."""
        step = self._handler.get_step(self._current_step)

        if step.name in ("mcp", "skills"):
            return self._multi_select_values

        # Check for option list (IDs are now like "option-list-provider")
        option_list = self.query(f"#option-list-{step.name}")
        if option_list:
            list_view = option_list.first()
            if list_view and list_view.highlighted_child:
                # Extract value from id (e.g., "opt-provider-openai" -> "openai")
                item_id = list_view.highlighted_child.id
                prefix = f"opt-{step.name}-"
                if item_id and item_id.startswith(prefix):
                    return item_id[len(prefix):]

        # Check for text input (IDs are now like "step-input-user_name")
        input_widget = self.query(f"#step-input-{step.name}")
        if input_widget:
            return input_widget.first().value

        return step.get_default()

    def _go_back(self) -> None:
        """Go to the previous step."""
        if self._current_step > 0:
            self._show_step(self._current_step - 1)

    def _skip_step(self) -> None:
        """Skip the current optional step."""
        step = self._handler.get_step(self._current_step)
        # Store default/empty value
        self._handler.set_step_data(step.name, step.get_default())
        self._advance()

    def _go_next(self) -> None:
        """Validate and advance to the next step."""
        step = self._handler.get_step(self._current_step)
        value = self._get_current_value()

        # Validate
        is_valid, error = step.validate(value)
        if not is_valid:
            self.query_one("#step-error", Static).update(error or "Invalid input")
            return

        # Store value
        self._handler.set_step_data(step.name, value)

        self._advance()

    def _advance(self) -> None:
        """Advance to the next step or complete."""
        if self._current_step < self._handler.get_step_count() - 1:
            self._show_step(self._current_step + 1)
        else:
            self._complete()

    def _complete(self) -> None:
        """Complete the wizard and return to the app."""
        self._handler.on_complete(cancelled=False)
        self.app.pop_screen()

    def action_cancel(self) -> None:
        """Handle Escape key to cancel wizard."""
        self._handler.on_complete(cancelled=True)
        self.app.pop_screen()
