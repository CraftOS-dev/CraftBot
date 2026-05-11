
from __future__ import annotations
import json
import ast
import tempfile
import os
import hashlib
from gradio_client import Client, file
from typing import Dict, Optional, List, Tuple, Any
from agent_core import Action
from app.state.agent_state import STATE
from app.state.types import ReasoningResult
from agent_core import TodoItem
from app.gui.handler import GUIHandler
from app.prompt import GUI_REASONING_PROMPT, GUI_QUERY_FOCUSED_PROMPT, GUI_PIXEL_POSITION_PROMPT, GUI_REASONING_PROMPT_OMNIPARSER
from app.vlm_interface import VLMInterface
from agent_core import ActionManager, ActionLibrary, ActionRouter
from app.context_engine import ContextEngine
from app.event_stream import EventStreamManager
from app.llm import LLMInterface, LLMCallType
from app.logger import logger
from agent_core import profile, OperationCategory

# Hardcoded list of actions available in GUI mode
GUI_MODE_ACTIONS = [
    # Core actions (always available)
    "send_message",
    "wait",
    "set_mode",
    "task_update_todos",
    # GUI interaction actions
    "mouse_click",
    "mouse_move",
    "mouse_drag",
    "mouse_trace",
    "keyboard_type",
    "keyboard_hotkey",
    "scroll",
    "open_browser",
    "open_application",
    "window_control",
    "clipboard_read",
    "clipboard_write",
]

# Compact action space prompt for GUI mode 
# This is a hardcoded prompt that describes all available GUI actions in a compact format
GUI_ACTION_SPACE_PROMPT = """## Action Space

mouse_click(x=<int>, y=<int>, button='left', click_type='single') # Click at (x,y). button: 'left'|'right'|'middle'. click_type: 'single'|'double'.
mouse_move(x=<int>, y=<int>, duration=0) # Move cursor to (x,y). Optional duration in seconds for smooth move.
mouse_drag(start_x=<int>, start_y=<int>, end_x=<int>, end_y=<int>, duration=0.5) # Drag from start to end position.
mouse_trace(points=[{x, y, duration}, ...], relative=false, easing='linear') # Move through waypoints. easing: 'linear'|'easeInOutQuad'.
keyboard_type(text='<string>', interval=0) # Type text at current focus. Use \\n for Enter. interval=delay between keystrokes.
keyboard_hotkey(keys='<combo>') # Send key combo. Examples: 'ctrl+c', 'alt+tab', 'enter'. Use + to combine keys.
scroll(direction='<up|down>') # Scroll one viewport in direction.
open_browser(url='<url>') # Open browser, optionally with URL.
open_application(exe_path='<path>', args=[]) # Launch Windows app at exe_path with optional args.
window_control(operation='<op>', title='<substring>') # operation: 'focus'|'close'|'maximize'|'minimize'. Matches window by title substring.
clipboard_read() # Read current clipboard content.
clipboard_write(content='<string>') # Write text to clipboard.
send_message(message='<string>', wait_for_user_reply=false) # Send message to user. Set wait_for_user_reply=true to pause for response.
wait(seconds=<number>) # Pause for seconds (max 60).
set_mode(target_mode='<cli|gui>') # Switch agent mode. Use 'cli' when GUI task is complete.
task_update_todos(todos=[{content, status}, ...]) # Update todo list. status: 'pending'|'in_progress'|'completed'.
"""

class GUIModule:
    def __init__(
        self,
        provider: str = "byteplus",
        action_library: ActionLibrary = None,
        action_router: ActionRouter = None,
        context_engine: ContextEngine = None,
        action_manager: ActionManager = None,
        event_stream_manager: EventStreamManager = None,
        tui_footage_callback = None,
    ):
        # Read API key and base URL from settings.json
        from app.config import get_api_key, get_base_url
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        self.llm: LLMInterface = LLMInterface(provider=provider, api_key=api_key, base_url=base_url)
        self.vlm: VLMInterface = VLMInterface(provider=provider, api_key=api_key, base_url=base_url)
        self.action_library: ActionLibrary = action_library
        self.action_router: ActionRouter = action_router
        self.context_engine: ContextEngine = context_engine
        self.action_manager: ActionManager = action_manager
        self.event_stream_manager: EventStreamManager = event_stream_manager
        self._tui_footage_callback = tui_footage_callback

        # ==================================
        #  CONFIG - Read from settings.json
        # ==================================
        from app.config import get_settings
        gui_settings = get_settings().get("gui", {})
        omniparser_base_url: str = gui_settings.get("omniparser_url", "http://127.0.0.1:7861")
        use_omniparser: bool = gui_settings.get("use_omniparser", False)

        self.can_use_omniparser: bool = use_omniparser and (omniparser_base_url is not None)
        logger.info(f"[can_use_omniparser]: {self.can_use_omniparser}")

        if self.can_use_omniparser:
            self.gradio_client: Client | None = Client(omniparser_base_url)
        else:
            self.gradio_client: Client | None = None

        # ==================================
        #  ACTION TRACKING FOR LOOP DETECTION
        # ==================================
        # Track recent actions to detect repeated failures
        self._recent_actions: List[Dict[str, Any]] = []
        self._max_action_history = 10  # Keep last 10 actions
        self._repetition_threshold = 2  # Warn after 2 similar actions
        self._coordinate_tolerance = 30  # Pixels within which coordinates are considered "same"

        # ==================================
        #  OMNIPARSER CACHE
        # ==================================
        self._omniparser_cache: Dict[str, Any] = {
            "screenshot_hash": None,
            "image_description_list": None,
            "annotated_image_bytes": None
        }

    def set_tui_footage_callback(self, callback) -> None:
        """Set the TUI footage callback for screen display."""
        self._tui_footage_callback = callback

    def switch_to_gui_mode(self) -> None:
        STATE.update_gui_mode(True)

    def switch_to_cli_mode(self) -> None:
        STATE.update_gui_mode(False)

    def log_gui_reasoning(self, reasoning: str, session_id: Optional[str] = None) -> None:
        """Log agent reasoning to task-specific event stream."""
        if self.event_stream_manager:
            self.event_stream_manager.log(
                "agent reasoning",
                reasoning,
                severity="DEBUG",
                task_id=session_id,
            )

    def _track_action(self, action_name: str, params: Dict[str, Any]) -> None:
        """Track an action for loop detection."""
        action_record = {
            "action_name": action_name,
            "x": params.get("x"),
            "y": params.get("y"),
        }
        self._recent_actions.append(action_record)
        # Keep only last N actions
        if len(self._recent_actions) > self._max_action_history:
            self._recent_actions = self._recent_actions[-self._max_action_history:]

    def _check_for_repeated_action(self, action_name: str, params: Dict[str, Any]) -> Optional[str]:
        """
        Check if the proposed action is a repeat of recent failed actions.
        Returns a warning message if repetition detected, None otherwise.
        """
        if action_name not in ["mouse_click", "mouse_move", "mouse_drag"]:
            return None

        proposed_x = params.get("x")
        proposed_y = params.get("y")
        if proposed_x is None or proposed_y is None:
            return None

        # Count similar actions in recent history
        similar_count = 0
        for past_action in self._recent_actions:
            if past_action["action_name"] == action_name:
                past_x = past_action.get("x")
                past_y = past_action.get("y")
                if past_x is not None and past_y is not None:
                    # Check if coordinates are within tolerance
                    if (abs(proposed_x - past_x) <= self._coordinate_tolerance and
                        abs(proposed_y - past_y) <= self._coordinate_tolerance):
                        similar_count += 1

        if similar_count >= self._repetition_threshold:
            warning = (
                f"WARNING: Action '{action_name}' at coordinates near ({proposed_x}, {proposed_y}) "
                f"has been attempted {similar_count} times without apparent success. "
                f"Try a different approach: adjust coordinates significantly (50+ pixels), "
                f"use keyboard navigation (Tab/Enter), click a different element, "
                f"or use send_message to inform the user about the difficulty."
            )
            return warning

        return None

    def _inject_warning_to_event_stream(self, warning: str, session_id: Optional[str] = None) -> None:
        """Inject a warning message to the task-specific event stream."""
        if self.event_stream_manager and warning:
            self.event_stream_manager.log(
                "loop_detection_warning",
                warning,
                severity="WARNING",
                task_id=session_id,
            )
            logger.warning(f"[GUI LOOP DETECTION] {warning}")

    async def perform_gui_task_step(self, step: Optional[TodoItem], session_id: str, next_action_description: str, parent_action_id: str) -> dict:
        """
        Perform a GUI task step. Keeps calling the action until the next action is not None. When the next action is not None, it returns the response.
        If next action is None, it means the task is complete, and it returns the response.

        Args:
            step: The current todo item (optional).
            session_id: The session ID.
            next_action_description: The next action description.
            parent_action_id: The parent action ID.
        """
        logger.info(f"[PERFORM GUI TASK STEP] {step} {session_id} {next_action_description} {parent_action_id}")
        try:
            self.switch_to_gui_mode()
            STATE.set_agent_property(
                "current_task_id", session_id)

            response: dict = {
                "status": "ok",
                "message": "Action completed successfully",
                "action_output": None,
            }

            response: dict = await self._perform_gui_task_step_action(step, session_id, next_action_description, parent_action_id)
            logger.info(f"[GUI TASK STEP ACTION RESPONSE] {response}")

            return response

        except Exception as e:
            logger.error(f"[GUI TASK ERROR] {e}", exc_info=True)
            raise

    # ===================================
    # Private Methods
    # ===================================

    @profile("gui_perform_task_step_action", OperationCategory.ACTION_EXECUTION)
    async def _perform_gui_task_step_action(self, step: Optional[TodoItem], session_id: str, next_action_description: str, parent_action_id: str) -> dict:
        """
        Perform a GUI task step action.

        Reasoning is now integrated into action selection, reducing LLM calls.
        New flow:
        1. Take screenshot
        2. Get image description (VLM call)
        3. Select action with integrated reasoning (LLM call) → reasoning, element_index_to_find, action_name, parameters
        4. If element_index_to_find is provided, get pixel position (VLM call)
        5. Inject pixel position into parameters if needed
        6. Execute action

        Args:
            step: The current todo item (optional).
            session_id: The session ID.
            next_action_description: The next action description.
            parent_action_id: The parent action ID.
        """
        try:
            query: str = next_action_description
            parent_id = parent_action_id

            # ===================================
            # 1. Check Limits
            # ===================================
            if not await self._check_agent_limits():
                self.switch_to_cli_mode()
                return {
                    "status": "error",
                    "message": "Agent limits reached"
                }

            # ===================================
            # 2. Take Screenshot
            # ===================================
            png_bytes = GUIHandler.get_screen_state(GUIHandler.TARGET_CONTAINER)
            if png_bytes is None:
                return {
                    "status": "error",
                    "message": "Failed to take screenshot"
                }

            # Push screenshot to TUI for display
            if self._tui_footage_callback and png_bytes:
                try:
                    await self._tui_footage_callback(png_bytes, GUIHandler.TARGET_CONTAINER)
                except Exception as e:
                    logger.debug(f"[GUI] Failed to push footage to TUI: {e}")

            # ===================================
            # 3. Get Image Description + Prepare Image for VLM
            # ===================================
            if self.can_use_omniparser:
                reasoning_result, action_query = await self.omniparser_flow(query=query, png_bytes=png_bytes)
            else:
                reasoning_result, action_query = await self.vlm_flow(query=query, png_bytes=png_bytes)

            vlm_reasoning: str = reasoning_result.reasoning
            vlm_action_query: str = action_query

            # Log VLM reasoning to event stream (before action selection)
            if self.event_stream_manager and vlm_reasoning:
                self.log_gui_reasoning(vlm_reasoning + " This is the action I will execute: " + vlm_action_query, session_id=session_id)

            # ===================================
            # 4. Select Action (with integrated reasoning via VLM)
            # ===================================
            action_decision = await self.action_router.select_action_in_GUI(query=action_query, reasoning=vlm_reasoning, GUI_mode=True)

            if not action_decision:
                raise ValueError("Action router returned no decision.")

            action_name = action_decision.get("action_name")
            action_params = action_decision.get("parameters", {})

            logger.info(f"[GUI VLM REASONING] {vlm_reasoning}")
            logger.info(f"[GUI ACTION QUERY] {vlm_action_query}")

            if not action_name:
                raise ValueError("No valid action selected by the router.")

            # ===================================
            # 5. Check for Repeated Actions (Loop Detection)
            # ===================================
            warning = self._check_for_repeated_action(action_name, action_params)
            if warning:
                self._inject_warning_to_event_stream(warning, session_id=session_id)

            # Retrieve action
            action: Optional[Action] = self.action_library.retrieve_action(action_name)
            if action is None:
                raise ValueError(
                    f"Action '{action_name}' not found in the library. "
                    "Check DB connectivity or ensure the action is registered."
                )

            # ===================================
            # 6. Execute Action
            # ===================================
            action_output = await self.action_manager.execute_action(
                action=action,
                context=vlm_action_query if vlm_action_query else query,
                event_stream=self.context_engine.get_event_stream(),
                parent_id=parent_id,
                session_id=session_id,
                is_running_task=True,
                is_gui_task=True,
                input_data=action_params,
            )

            # ===================================
            # 7. Track Action for Loop Detection
            # ===================================
            self._track_action(action_name, action_params)

            return {
                "status": "ok",
                "message": "Action completed successfully",
                "action_output": action_output
            }

        except Exception as e:
            logger.error(f"[GUI TASK STEP ERROR] {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
            }

    async def vlm_flow(self, query: str, png_bytes: bytes) -> Tuple[ReasoningResult, str]:
        """
        Perform the VLM flow.
        """
        # ==================================
        # 1. Get Image Description
        # ==================================
        image_description: str = await self._get_image_description_vlm(png_bytes=png_bytes, query=query)

        # ==================================
        # 2. Perform Reasoning
        # ==================================
        reasoning_result: ReasoningResult = await self._perform_reasoning_GUI_vlm(query=image_description)
        action_query: str = reasoning_result.action_query

        # ==================================
        # 3. Get Pixel Position
        # ==================================
        pixel_position: List[int] = await self._get_pixel_position_vlm(image_bytes=png_bytes, element_to_find=action_query)

        # ==================================
        # 4. Construct Action Search Query
        # ==================================
        action_search_query: str = action_query + " " + json.dumps(pixel_position)

        return reasoning_result, action_search_query

    async def omniparser_flow(self, query: str, png_bytes: bytes) -> Tuple[ReasoningResult, str]:
        """
        Perform the omniparser flow.
        """
        # ==================================
        # 1. OmniParser Image Analysis
        # ==================================
        # Check OmniParser cache - reuse if screenshot unchanged
        current_hash = hashlib.md5(png_bytes).hexdigest()
        if current_hash == self._omniparser_cache["screenshot_hash"]:
            # Cache hit - reuse previous results
            image_description_list = self._omniparser_cache["image_description_list"]
            annotated_image_bytes = self._omniparser_cache["annotated_image_bytes"]
            logger.info("[GUI] Using cached OmniParser results (screenshot unchanged)")
        else:
            # Cache miss - call OmniParser and update cache
            image_description_list, annotated_image_bytes = await self._get_image_description_omniparser(png_bytes)
            self._omniparser_cache = {
                "screenshot_hash": current_hash,
                "image_description_list": image_description_list,
                "annotated_image_bytes": annotated_image_bytes
            }
            logger.debug("[GUI] OmniParser cache updated with new screenshot")

        image_description_list, annotated_image_bytes = await self._get_image_description_omniparser(png_bytes)

        # ==================================
        # 2. Reasoning
        # ==================================
        reasoning_result, item_index = await self._perform_reasoning_GUI_omniparser(png_bytes=annotated_image_bytes)
        action_query: str = reasoning_result.action_query

        # ==================================
        # 3. Get Pixel Position
        # ==================================
        if len(image_description_list) > item_index:
            item = image_description_list[item_index]
            bbox: List[float] = self.extract_bbox_from_line(item)
            pixel_position: List[int] = self.convert_bbox_to_pixels(bbox, 1064, 1064)
            action_query += ". The element involved has a position of [xmin_px, ymin_px, xmax_px, ymax_px] = " + json.dumps(pixel_position)
        else:
            pixel_position = ". No UI element needed for action."
            action_query += pixel_position

        # ==================================
        # 4. Construct Action Search Query
        # ==================================
        
        return reasoning_result, action_query

    # ==================================
    # VLM Helper Methods
    # ==================================

    @profile("gui_get_image_description_vlm", OperationCategory.LLM)
    async def _get_image_description_vlm(self, png_bytes: bytes, query: str) -> str:
        """
        Get the description of the image.
        """
        system_prompt, _ = self.context_engine.make_prompt(
            user_flags={"query": False, "expected_output": False},
            system_flags={
                "policy": False, 
                "event_stream": False, 
                "task_state": False, 
                "conversation_history": False, 
                "agent_info": False, 
                "role_info": False, 
                "agent_state": False, 
                "base_instruction": False,
                "environment": False,
            }
        )

        user_prompt = GUI_QUERY_FOCUSED_PROMPT.format(query=query)

        image_description: str = await self.vlm.generate_response_async(
            image_bytes=png_bytes,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            debug=True,
        )

        return image_description

    @profile("gui_perform_reasoning_vlm", OperationCategory.REASONING)
    async def _perform_reasoning_GUI_vlm(self, query: str, retries: int = 2, log_reasoning_event = False) -> ReasoningResult:
        """
        Perform LLM-based reasoning on a user query to guide action selection.

        This function calls an asynchronous LLM API, validates its structured JSON
        response, and retries if the output is malformed.

        Args:
            query (str): The raw user query from the user.
            retries (int): Number of retry attempts if the LLM returns invalid JSON.

        Returns:
            ReasoningResult: A validated reasoning result containing:
                - reasoning: The model's reasoning output
                - action_query: A refined query used for action selection
        """
        # Build the system prompt using the current context configuration
        system_prompt, _ = self.context_engine.make_prompt(
            user_flags={"query": False, "expected_output": False},
            system_flags={"policy": False, "event_stream": False, "task_state": False, "agent_state": False},
        )
        # Format the user prompt with context for proper reasoning
        # GUI_REASONING_PROMPT requires: gui_event_stream, task_state, agent_state, gui_state
        prompt = GUI_REASONING_PROMPT.format(
            gui_event_stream=self.context_engine.get_event_stream(),
            task_state=self.context_engine.get_task_state(),
            agent_state=self.context_engine.get_agent_state(),
            gui_state=query,
        )

        # Attempt the LLM call and parsing up to (retries + 1) times
        for attempt in range(retries + 1):            
            response = await self.llm.generate_response_async(
                system_prompt=system_prompt,
                user_prompt=prompt,
            )

            try:
                # Parse and validate the structured JSON response
                reasoning_result, _ = self._parse_reasoning_response(response)

                if self.event_stream_manager and log_reasoning_event:
                    self.log_gui_reasoning(reasoning_result.reasoning)

                return reasoning_result
            except ValueError as e:                
                raise RuntimeError("Failed to obtain valid reasoning from VLM") from e

    @profile("gui_get_pixel_position_vlm", OperationCategory.LLM)
    async def _get_pixel_position_vlm(self, image_bytes: bytes, element_to_find: str) -> List[Dict]:
        """
        Get the pixel position of the element in the image.
        """
        prompt = GUI_PIXEL_POSITION_PROMPT.format(element_to_find=element_to_find)
        system_prompt, _ = self.context_engine.make_prompt(
            user_flags={"query": False, "expected_output": False},
            system_flags={
                "policy": False, 
                "event_stream": False, 
                "task_state": False, 
                "conversation_history": False, 
                "agent_info": False, 
                "role_info": False, 
                "agent_state": False, 
                "base_instruction": False, 
                "environment": False,
            }
        )
        response = await self.vlm.generate_response_async(image_bytes, system_prompt=system_prompt, user_prompt=prompt)
        try:
            parsed: List[Dict] = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {response}") from e
        return parsed

    # ==================================
    # OmniParser Helper Methods
    # ==================================
    
    @profile("gui_get_image_description_omniparser", OperationCategory.LLM)
    async def _get_image_description_omniparser(self, image_bytes: bytes) -> Tuple[List[str], bytes]:
        """
        Get the description of the image using OmniParser via Gradio Client.
        """
        print("Sending request to OmniParser (Gradio 4.x)...")

        # --- 1. Prepare Input Data ---
        input_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        try:
            # Write the raw bytes to the temp file
            input_tmp.write(image_bytes)
            input_tmp.close() # Close file so client can read it

            # --- 2. Make the Prediction Call  ---
            result = self.gradio_client.predict(
                file(input_tmp.name),
                0.05,              # Input 1: box_threshold
                0.1,               # Input 2: iou_threshold
                False,             # Input 3: use_paddleocr
                640,               # Input 4: imgsz
                api_name="/process"
            )
            # 'result' is a list: [path_to_downloaded_output_image, parsed_text_string]

        except Exception as e:
            raise ValueError(f"Gradio API call failed: {e}") from e
        finally:
            # Clean up the input temp file regardless of success/failure
            if os.path.exists(input_tmp.name):
                # We put this in a try block just in case another process locked it
                try: os.remove(input_tmp.name)
                except Exception: pass

        # --- 3. Parse Response ---
        try:
            # A) Extract Text Content (Index 1)
            raw_text_block = str(result[1]).strip()
            parsed_text_list = [line for line in raw_text_block.splitlines() if line.strip()]

            # B) Extract Annotated Image Bytes (Index 0)
            # Gradio client saves the output image to a temporary file path on disk.
            output_temp_path = result[0]

            if not os.path.exists(output_temp_path):
                 raise ValueError(f"Result image file not found at: {output_temp_path}")

            # Read bytes off disk
            with open(output_temp_path, "rb") as f:
                annotated_image_bytes = f.read()

            # Clean up output temp file
            try: os.remove(output_temp_path)
            except Exception: pass

            return parsed_text_list, annotated_image_bytes

        except (IndexError, TypeError, IOError, OSError) as e:
             raise ValueError(f"Failed to parse Gradio client response format: {e}") from e

    @profile("gui_perform_reasoning_omniparser", OperationCategory.REASONING)
    async def _perform_reasoning_GUI_omniparser(self, png_bytes: bytes, retries: int = 2, log_reasoning_event = False) -> Tuple[ReasoningResult, int]:
        """
        Perform reasoning on a image to guide action selection.

        Input:
            - png_bytes: The PNG bytes of the image.
            - retries: The number of retry attempts if the reasoning fails.
            - log_reasoning_event: Whether to log the reasoning event.

        Output:
            - reasoning_result: The reasoning result.
            - item_index: The index of the item in the image.
        """
        # Build the system prompt using the current context configuration
        system_prompt, _ = self.context_engine.make_prompt(
            user_flags={"query": False, "expected_output": False},
            system_flags={"policy": False, "event_stream": False, "task_state": False, "agent_state": False},
        )
        # Format the user prompt with context for proper reasoning
        # GUI_REASONING_PROMPT_OMNIPARSER requires: event_stream, task_state, agent_state
        prompt = GUI_REASONING_PROMPT_OMNIPARSER.format(
            event_stream=self.context_engine.get_event_stream(),
            task_state=self.context_engine.get_task_state(),
            agent_state=self.context_engine.get_agent_state(),
        )

        # Attempt the LLM call and parsing up to (retries + 1) times
        for attempt in range(retries + 1):            
            response = await self.vlm.generate_response_async(
                image_bytes=png_bytes,
                system_prompt=system_prompt,
                user_prompt=prompt,
            )

            try:
                # Parse and validate the structured JSON response
                reasoning_result, item_index = self._parse_reasoning_response(response)

                if self.event_stream_manager and log_reasoning_event:
                    self.log_gui_reasoning(reasoning_result.reasoning)

                return reasoning_result, item_index
            except ValueError as e:                
                raise RuntimeError("Failed to obtain valid reasoning from VLM") from e

    def extract_bbox_from_line(self, data_line: str) -> Optional[List[float]]:
        """
        Parses a single OmniParser data string and extracts the bounding box.

        Args:
            data_line: A single string, e.g., "icon 0: {'type': ... 'bbox': [...] ...}"

        Returns:
            A list of 4 floats representing [ymin, xmin, ymax, xmax],
            or None if parsing fails.
        """
        try:
            # 1. Isolate the dictionary part of the string.
            # The line always starts with "icon N: {...", so we split at the first ": "
            parts = data_line.split(': ', 1)

            if len(parts) < 2:
                logger.warning(f"Error: Line format incorrect. Could not find separator ': '")
                return None

            # parts[0] is like "icon 0"
            # parts[1] is like "{'type': 'text', 'bbox': [...] ...}"
            dict_string_representation = parts[1].strip()

            # 2. Convert the string representation into a real Python dictionary.
            # ast.literal_eval safely evaluates strings containing Python literals.
            real_dictionary = ast.literal_eval(dict_string_representation)

            # 3. Extract the 'bbox' key.
            # We use .get() to avoid crashing if 'bbox' is somehow missing.
            bbox = real_dictionary.get('bbox')

            # Basic validation to ensure it looks like a bbox (list of 4 items)
            if isinstance(bbox, list) and len(bbox) == 4:
                return bbox
            else:
                logger.warning(f"Error: 'bbox' found but format is invalid: {bbox}")
                return None

        except (ValueError, SyntaxError, ast.ASTError) as e:
            logger.warning(f"Error parsing dictionary contents in line: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error: {e}")
            return None

    def convert_bbox_to_pixels(
        self,
        relative_bbox: List[float],
        img_width: int,
        img_height: int
    ) -> List[int]:
        """
        Converts normalized [ymin, xmin, ymax, xmax] to [ymin_px, xmin_px, ymax_px, xmax_px].

        Args:
            relative_bbox: List of 4 floats between 0.0 and 1.0 [ymin, xmin, ymax, xmax].
            img_width: The total width of the original image in pixels.
            img_height: The total height of the original image in pixels.

        Returns:
            List of 4 integers representing pixel coordinates.
        """
        # Unpack normalized coordinates
        ymin_rel, xmin_rel, ymax_rel, xmax_rel = relative_bbox

        # Calculate pixel coordinates.
        # We use int() to truncate decimals, which is standard for pixel grid coordinates.
        # Sometimes round() is used depending on precision needs, but int() is safer to stay within bounds.
        xmin_px = int(xmin_rel * img_width)
        xmax_px = int(xmax_rel * img_width)

        ymin_px = int(ymin_rel * img_height)
        ymax_px = int(ymax_rel * img_height)

        # Ensure coordinates don't go below zero just in case of weird float math
        xmin_px = max(0, xmin_px)
        ymin_px = max(0, ymin_px)

        # Return in the same order [ymin, xmin, ymax, xmax]
        return [ymin_px, xmin_px, ymax_px, xmax_px]

    # ==================================
    # Global Helper Methods
    # ==================================

    def _parse_reasoning_response(self, response: str) -> Tuple[ReasoningResult, int]:
        """
        Parse and validate the structured JSON response from the reasoning VLM call.
        """
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"VLM returned invalid JSON: {response}") from e

        if not isinstance(parsed, dict):
            raise ValueError(f"VLM response is not a JSON object: {parsed}")

        reasoning = parsed.get("reasoning")
        action_query = parsed.get("action_query")
        item_index = parsed.get("item_index", 0)

        if not isinstance(reasoning, str) or not isinstance(action_query, str):
            raise ValueError(f"Invalid reasoning schema: {parsed}")
        if not isinstance(item_index, int):
            raise ValueError(f"Invalid item index: {item_index}")

        reasoning_result = ReasoningResult(
            reasoning=reasoning,
            action_query=action_query,
        )
        return reasoning_result, int(item_index)

    async def _check_agent_limits(self) -> bool:
        agent_properties = STATE.get_agent_properties()
        action_count: int = agent_properties.get("action_count", 0)
        max_actions: int = agent_properties.get("max_actions_per_task", 0)
        token_count: int = agent_properties.get("token_count", 0)
        max_tokens: int = agent_properties.get("max_tokens_per_task", 0)

        # Check action limits - returns False to switch to CLI mode,
        # where the agent_base's _check_agent_limits will handle the
        # pause-and-ask flow with user options.
        if (action_count / max_actions) >= 1.0:
            return False

        # Check token limits
        if (token_count / max_tokens) >= 1.0:
            return False

        # No limits close or reached
        return True