"""
WhatsApp Web helpers using Playwright (headless Chrome) for connecting any WhatsApp number via QR code.

This module provides functionality for:
- Starting WhatsApp Web sessions in headless Chrome
- Capturing QR codes for pairing
- Sending/receiving messages via WhatsApp Web
- Managing session persistence

Dependencies:
    pip install playwright
    playwright install chromium

Note: This is for personal WhatsApp accounts. For business use, prefer the WhatsApp Business API.
"""

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any, Tuple
from datetime import datetime

from agent_core.utils.logger import logger


def _normalize_name(name: str) -> str:
    """Normalize a name for comparison: lowercase, remove extra spaces, strip punctuation."""
    # Lowercase and strip
    name = name.lower().strip()
    # Remove common punctuation but keep spaces
    name = re.sub(r'[^\w\s]', '', name)
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    return name


def _get_name_words(name: str) -> List[str]:
    """Get normalized words from a name."""
    return _normalize_name(name).split()


def _fuzzy_name_match(search_query: str, contact_name: str, threshold: float = 0.7) -> Tuple[bool, float]:
    """
    Check if a search query fuzzy-matches a contact name.

    Returns (is_match, score) where:
    - is_match: True if the names are similar enough
    - score: Similarity score between 0 and 1

    Matching logic:
    1. If all search words are contained in the contact name (substring match), it's a match
    2. Otherwise, use sequence similarity with typo tolerance

    Examples:
    - "Emad Tavana" matches "Emad Tavana MDX" (all words contained) -> True, ~0.9
    - "Emad tavana" matches "Emad Tavana MDX" (case insensitive) -> True, ~0.9
    - "Emad Tavana" does NOT match "Emad Davane" (Tavana != Davane) -> False, ~0.6
    """
    search_words = _get_name_words(search_query)
    contact_words = _get_name_words(contact_name)

    if not search_words or not contact_words:
        return False, 0.0

    # Strategy 1: Check if all search words are contained in contact words
    # This handles "Emad Tavana" -> "Emad Tavana MDX"
    all_words_found = True
    word_match_scores = []

    for search_word in search_words:
        # Find the best matching word in contact
        best_word_score = 0.0
        for contact_word in contact_words:
            # Exact match
            if search_word == contact_word:
                best_word_score = 1.0
                break
            # Substring match (e.g., "tav" in "tavana")
            if search_word in contact_word or contact_word in search_word:
                score = min(len(search_word), len(contact_word)) / max(len(search_word), len(contact_word))
                best_word_score = max(best_word_score, score)
            # Fuzzy word match for typos
            else:
                ratio = SequenceMatcher(None, search_word, contact_word).ratio()
                best_word_score = max(best_word_score, ratio)

        word_match_scores.append(best_word_score)
        # A word is "found" if it matches well enough (>= 0.8 for individual words)
        if best_word_score < 0.8:
            all_words_found = False

    # Calculate overall score
    if word_match_scores:
        avg_word_score = sum(word_match_scores) / len(word_match_scores)
    else:
        avg_word_score = 0.0

    # Also calculate full string similarity as a secondary metric
    full_similarity = SequenceMatcher(
        None,
        _normalize_name(search_query),
        _normalize_name(contact_name)
    ).ratio()

    # Combined score: weight word matching higher
    combined_score = (avg_word_score * 0.7) + (full_similarity * 0.3)

    # It's a match if:
    # 1. All search words were found in the contact name, OR
    # 2. The combined score is above threshold
    is_match = all_words_found or combined_score >= threshold

    return is_match, combined_score

# Session storage directory
WHATSAPP_WEB_SESSIONS_DIR = Path(__file__).parent.parent.parent.parent.parent / ".whatsapp_web_sessions"


@dataclass
class WhatsAppWebSession:
    """Represents an active WhatsApp Web session."""
    session_id: str
    user_id: str
    jid: Optional[str] = None
    phone_number: Optional[str] = None
    status: str = "initializing"  # initializing, qr_ready, connected, disconnected, error
    qr_code: Optional[str] = None
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None


class WhatsAppWebManager:
    """
    Manages WhatsApp Web sessions using Playwright (headless Chrome).

    Usage:
        manager = WhatsAppWebManager()
        session = await manager.create_session(user_id="user123")
        # QR code will be available in session.qr_code
        # Poll session.status until "connected"
    """

    def __init__(self):
        self._sessions: Dict[str, WhatsAppWebSession] = {}
        self._browsers: Dict[str, Any] = {}  # session_id -> browser
        self._pages: Dict[str, Any] = {}  # session_id -> page
        self._chat_previews: Dict[str, str] = {}  # chat_name -> last seen preview text
        self._playwright_loop: Optional[asyncio.AbstractEventLoop] = None  # loop where Playwright was started
        self._ensure_sessions_dir()

    async def run_on_playwright_loop(self, coro):
        """Run a coroutine on the event loop where Playwright was started.

        When Playwright is started on the main event loop and actions are executed
        on worker threads (each with their own event loop), Playwright calls fail
        with "The future belongs to a different loop". This method dispatches the
        coroutine to the correct loop using run_coroutine_threadsafe.

        If we're already on the Playwright loop (or no loop was recorded), the
        coroutine is awaited directly.
        """
        import concurrent.futures

        if self._playwright_loop is None:
            return await coro

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is self._playwright_loop:
            return await coro

        # We're on a different loop — dispatch to the Playwright loop
        future = asyncio.run_coroutine_threadsafe(coro, self._playwright_loop)
        # Block the current thread until the result is ready (with timeout)
        return future.result(timeout=120)

    def _ensure_sessions_dir(self):
        """Create sessions directory if it doesn't exist."""
        WHATSAPP_WEB_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    def _get_session_path(self, session_id: str) -> Path:
        """Get the path for session data storage (browser profile)."""
        return WHATSAPP_WEB_SESSIONS_DIR / session_id

    async def create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        on_qr_code: Optional[Callable[[str], None]] = None,
        on_connected: Optional[Callable[[str, str], None]] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
    ) -> WhatsAppWebSession:
        """
        Create a new WhatsApp Web session using Playwright.

        Args:
            user_id: The user ID to associate with this session
            session_id: Optional session ID (generated if not provided)
            on_qr_code: Callback when QR code is available (receives base64 QR image)
            on_connected: Callback when connected (receives JID and phone number)
            on_disconnected: Callback when disconnected

        Returns:
            WhatsAppWebSession object with status and QR code info
        """
        import uuid

        if session_id is None:
            session_id = str(uuid.uuid4())

        session = WhatsAppWebSession(
            session_id=session_id,
            user_id=user_id,
            status="initializing",
            created_at=datetime.utcnow(),
        )
        self._sessions[session_id] = session

        try:
            from playwright.async_api import async_playwright

            logger.info(f"[WhatsApp Web] Starting Playwright session {session_id}")

            # Start browser with persistent context for session storage
            session_path = str(self._get_session_path(session_id))

            playwright = await async_playwright().start()
            self._playwright_loop = asyncio.get_running_loop()

            # Use headless=False for debugging, or "new" headless mode which is less detectable
            # WhatsApp Web may block old headless mode
            browser = await playwright.chromium.launch_persistent_context(
                user_data_dir=session_path,
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',  # Avoid detection
                ],
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
                locale='en-US',
            )

            self._browsers[session_id] = (playwright, browser)

            # Get the default page or create new one
            pages = browser.pages
            if pages:
                page = pages[0]
            else:
                page = await browser.new_page()
            self._pages[session_id] = page

            # Navigate to WhatsApp Web
            logger.info(f"[WhatsApp Web] Navigating to WhatsApp Web for session {session_id}")
            await page.goto('https://web.whatsapp.com', wait_until='domcontentloaded', timeout=60000)

            # Start background task to monitor for QR code and connection
            asyncio.create_task(self._monitor_session(session_id, session, on_qr_code, on_connected, on_disconnected))

            return session

        except ImportError as e:
            logger.error(f"[WhatsApp Web] Playwright not installed: {e}")
            logger.warning("[WhatsApp Web] Install with: pip install playwright && playwright install chromium")
            session.status = "error"
            session.qr_code = None
            return session

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to create session: {e}", exc_info=True)
            session.status = "error"
            return session

    async def _monitor_session(
        self,
        session_id: str,
        session: WhatsAppWebSession,
        on_qr_code: Optional[Callable],
        on_connected: Optional[Callable],
        on_disconnected: Optional[Callable],
    ):
        """Monitor the WhatsApp Web page for QR code and connection status."""
        logger.info(f"[WhatsApp Web] Starting monitor task for session {session_id}")

        page = self._pages.get(session_id)
        if not page:
            logger.error(f"[WhatsApp Web] No page found for session {session_id}")
            session.status = "error"
            return

        qr_captured = False
        max_attempts = 60  # 2 minutes timeout (2 sec intervals)
        attempts = 0

        # Wait for page to fully load first
        try:
            logger.info(f"[WhatsApp Web] Waiting for page to load for session {session_id}")
            await page.wait_for_load_state('networkidle', timeout=30000)
            logger.info(f"[WhatsApp Web] Page loaded for session {session_id}")

            # Give WhatsApp Web extra time to render QR code
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[WhatsApp Web] Page load wait timed out: {e}")

        while attempts < max_attempts and session_id in self._sessions:
            try:
                attempts += 1

                if attempts % 5 == 1:
                    logger.info(f"[WhatsApp Web] Monitor attempt {attempts} for session {session_id}, current status: {session.status}")

                # Check if already logged in (main chat interface visible)
                is_logged_in = await page.locator('[data-testid="chat-list"]').count() > 0
                if not is_logged_in:
                    # Alternative selectors for logged-in state
                    is_logged_in = await page.locator('div[data-tab="3"]').count() > 0
                if not is_logged_in:
                    # Another alternative - side panel
                    is_logged_in = await page.locator('#side').count() > 0

                if is_logged_in:
                    session.status = "connected"
                    session.last_activity = datetime.utcnow()
                    logger.info(f"[WhatsApp Web] Session {session_id} connected!")

                    # Try to get phone number from profile
                    try:
                        # Click on profile to get phone number
                        profile_btn = page.locator('[data-testid="menu-bar-user-avatar"]')
                        if await profile_btn.count() > 0:
                            await profile_btn.click()
                            await asyncio.sleep(1)
                            # Look for phone number text
                            phone_elem = page.locator('[data-testid="drawer-middle-info-phone"]')
                            if await phone_elem.count() > 0:
                                session.phone_number = await phone_elem.text_content()
                                session.jid = f"{session.phone_number.replace('+', '').replace(' ', '')}@s.whatsapp.net"
                    except Exception as e:
                        logger.debug(f"[WhatsApp Web] Could not get phone number: {e}")

                    if on_connected:
                        on_connected(session.jid or "", session.phone_number or "")
                    return

                # Try multiple QR code selectors
                qr_selectors = [
                    'canvas[aria-label="Scan this QR code to link a device!"]',
                    'canvas[aria-label*="QR"]',
                    'canvas[aria-label*="qr"]',
                    '[data-testid="qrcode"]',
                    'div[data-ref] canvas',  # WhatsApp uses data-ref for QR container
                    'canvas',  # Last resort - any canvas
                ]

                qr_found = False
                for selector in qr_selectors:
                    try:
                        qr_elem = page.locator(selector).first
                        if await qr_elem.count() > 0:
                            # Make sure it's visible and has reasonable size
                            box = await qr_elem.bounding_box()
                            if box and box['width'] > 50 and box['height'] > 50:
                                qr_screenshot = await qr_elem.screenshot()
                                qr_base64 = f"data:image/png;base64,{base64.b64encode(qr_screenshot).decode()}"

                                session.qr_code = qr_base64
                                session.status = "qr_ready"
                                qr_found = True

                                if not qr_captured:
                                    logger.info(f"[WhatsApp Web] QR code captured for session {session_id} using selector: {selector}")
                                    qr_captured = True
                                    if on_qr_code:
                                        on_qr_code(qr_base64)
                                break
                    except Exception as e:
                        continue

                # Log page state for debugging if no QR found after several attempts
                if not qr_found and attempts == 5:
                    try:
                        page_title = await page.title()
                        page_url = page.url
                        logger.info(f"[WhatsApp Web] Page state - title: {page_title}, url: {page_url}")

                        # Check for loading indicator
                        loading = await page.locator('[data-testid="startup"]').count()
                        if loading > 0:
                            logger.info(f"[WhatsApp Web] WhatsApp is still loading...")
                    except Exception as e:
                        logger.debug(f"[WhatsApp Web] Could not get page state: {e}")

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"[WhatsApp Web] Error monitoring session {session_id}: {e}", exc_info=True)
                await asyncio.sleep(2)

        # Timeout reached
        if session.status != "connected":
            session.status = "error"
            logger.warning(f"[WhatsApp Web] Session {session_id} timed out waiting for QR scan")

    def get_session(self, session_id: str) -> Optional[WhatsAppWebSession]:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_user_sessions(self, user_id: str) -> List[WhatsAppWebSession]:
        """Get all sessions for a user."""
        return [s for s in self._sessions.values() if s.user_id == user_id]

    async def disconnect_session(self, session_id: str) -> bool:
        """Disconnect and remove a session."""
        # Close browser
        if session_id in self._browsers:
            try:
                playwright, browser = self._browsers[session_id]
                await browser.close()
                await playwright.stop()
            except Exception as e:
                logger.error(f"[WhatsApp Web] Error closing browser for session {session_id}: {e}")
            del self._browsers[session_id]

        if session_id in self._pages:
            del self._pages[session_id]

        if session_id in self._sessions:
            del self._sessions[session_id]

        # Optionally remove session data directory
        # session_path = self._get_session_path(session_id)
        # if session_path.exists():
        #     import shutil
        #     shutil.rmtree(session_path)

        return True

    def list_persisted_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions that have persisted data on disk (can be reconnected)."""
        sessions = []
        if WHATSAPP_WEB_SESSIONS_DIR.exists():
            for session_dir in WHATSAPP_WEB_SESSIONS_DIR.iterdir():
                if session_dir.is_dir():
                    sessions.append({
                        "session_id": session_dir.name,
                        "path": str(session_dir),
                        "is_active": session_dir.name in self._sessions,
                    })
        return sessions

    async def reconnect_session(
        self,
        session_id: str,
        user_id: str,
        on_connected: Optional[Callable[[str, str], None]] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """
        Reconnect to an existing WhatsApp Web session using persisted browser data.

        This is useful after agent restart when the WhatsApp link is still active
        on the phone but the browser session was lost.

        Args:
            session_id: The session ID to reconnect (must have data on disk)
            user_id: The user ID to associate with this session
            on_connected: Callback when connected
            on_disconnected: Callback when disconnected

        Returns:
            Dict with status and session info
        """
        session_path = self._get_session_path(session_id)

        if not session_path.exists():
            return {
                "success": False,
                "error": f"No persisted session data found for session_id: {session_id}",
                "hint": "Use start_session to create a new session with QR code"
            }

        # Check if already active
        if session_id in self._sessions:
            session = self._sessions[session_id]
            return {
                "success": True,
                "status": session.status,
                "session_id": session_id,
                "message": "Session already active"
            }

        try:
            from playwright.async_api import async_playwright

            logger.info(f"[WhatsApp Web] Reconnecting session {session_id} from persisted data")

            # Create session object
            session = WhatsAppWebSession(
                session_id=session_id,
                user_id=user_id,
                status="reconnecting",
                created_at=datetime.utcnow(),
            )
            self._sessions[session_id] = session

            # Launch browser with existing profile
            playwright = await async_playwright().start()
            self._playwright_loop = asyncio.get_running_loop()
            browser = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(session_path),
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',
                ],
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
                locale='en-US',
            )

            self._browsers[session_id] = (playwright, browser)

            # Get page
            pages = browser.pages
            if pages:
                page = pages[0]
            else:
                page = await browser.new_page()
            self._pages[session_id] = page

            # Navigate to WhatsApp Web
            logger.info(f"[WhatsApp Web] Navigating to WhatsApp Web for reconnect...")
            await page.goto('https://web.whatsapp.com', wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_load_state('networkidle', timeout=30000)

            # Wait for page to stabilize
            await asyncio.sleep(3)

            # Check if already logged in
            logged_in_selectors = [
                '[data-testid="chat-list"]',
                'div[data-tab="3"]',
                '#side',
            ]

            is_logged_in = False
            for selector in logged_in_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        is_logged_in = True
                        break
                except Exception:
                    continue

            if is_logged_in:
                session.status = "connected"
                session.last_activity = datetime.utcnow()
                logger.info(f"[WhatsApp Web] Session {session_id} reconnected successfully!")

                if on_connected:
                    on_connected(session.jid or "", session.phone_number or "")

                return {
                    "success": True,
                    "status": "connected",
                    "session_id": session_id,
                    "message": "Successfully reconnected to existing WhatsApp Web session"
                }
            else:
                # Check if QR code is shown (session expired on phone)
                qr_selectors = [
                    'canvas[aria-label="Scan this QR code to link a device!"]',
                    'canvas[aria-label*="QR"]',
                    '[data-testid="qrcode"]',
                ]

                needs_qr = False
                for selector in qr_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            needs_qr = True
                            break
                    except Exception:
                        continue

                if needs_qr:
                    session.status = "qr_required"
                    logger.warning(f"[WhatsApp Web] Session {session_id} requires new QR scan (link expired on phone)")
                    return {
                        "success": False,
                        "status": "qr_required",
                        "session_id": session_id,
                        "error": "WhatsApp Web session expired. The device was unlinked from your phone.",
                        "hint": "Go to WhatsApp > Linked Devices on your phone and check if this device is still linked. If not, start a new session."
                    }
                else:
                    session.status = "unknown"
                    return {
                        "success": False,
                        "status": "unknown",
                        "session_id": session_id,
                        "error": "Could not determine session state. WhatsApp Web may still be loading."
                    }

        except ImportError as e:
            logger.error(f"[WhatsApp Web] Playwright not installed: {e}")
            return {"success": False, "error": "Playwright not installed. Run: pip install playwright && playwright install chromium"}
        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to reconnect session: {e}", exc_info=True)
            # Clean up on failure
            if session_id in self._sessions:
                del self._sessions[session_id]
            if session_id in self._browsers:
                try:
                    playwright, browser = self._browsers[session_id]
                    await browser.close()
                    await playwright.stop()
                except Exception:
                    pass
                del self._browsers[session_id]
            if session_id in self._pages:
                del self._pages[session_id]
            return {"success": False, "error": str(e)}

    async def send_message(
        self,
        session_id: str,
        to: str,
        message: str,
    ) -> Dict[str, Any]:
        """
        Send a text message via WhatsApp Web.

        Args:
            session_id: The session ID to use
            to: Recipient phone number (with country code, e.g., "1234567890") or contact name
            message: The message text

        Returns:
            Dict with message ID and status
        """
        page = self._pages.get(session_id)
        session = self._sessions.get(session_id)

        if not page or not session or session.status != "connected":
            return {"success": False, "error": "Session not connected"}

        try:
            # 1. Resolve contact if 'to' contains letters
            import re
            if re.search(r'[a-zA-Z]', to):
                logger.info(f"[WhatsApp Web] Resolving contact name '{to}' inside send_message...")
                res = await self.resolve_contact_phone(session_id, to)
                if res.get("success"):
                    to = res.get("phone")
                    logger.info(f"[WhatsApp Web] Resolved to {to}")
                else:
                    return {"success": False, "error": f"Could not resolve contact '{to}': {res.get('error')}"}

            # Clean phone number
            phone = to.lstrip('+').replace(' ', '').replace('-', '')

            # Navigate to chat using URL scheme
            await page.goto(f'https://web.whatsapp.com/send?phone={phone}&text={message}')
            await page.wait_for_load_state('networkidle')

            # Wait for message input to be ready and the chat to load
            try:
                # Wait longer for chat to load
                await page.wait_for_selector('div[contenteditable="true"], div[data-testid="popup-controls-ok"]', timeout=30000)
            except Exception:
                logger.warning("[WhatsApp Web] Timed out waiting for chat to load via URL")

            # Check for invalid number popup
            popup = page.locator('div[data-testid="popup-controls-ok"]')
            if await popup.count() > 0:
                await popup.click()
                return {"success": False, "error": "Invalid phone number or chat not found via URL"}

            # Wait a bit for text to populate from URL param
            await asyncio.sleep(2)

            # Try multiple selectors for the send button (WhatsApp Web changes these frequently)
            send_selectors = [
                '[data-testid="send"]',
                '[data-icon="send"]',
                'button[aria-label="Send"]',
                'span[data-icon="send"]',
                '[aria-label="Send"]',
                'button:has(span[data-icon="send"])',
                'div[role="button"][aria-label="Send"]'
            ]

            send_clicked = False
            for selector in send_selectors:
                try:
                    send_btn = page.locator(selector)
                    if await send_btn.count() > 0:
                        await send_btn.first.click()
                        send_clicked = True
                        logger.info(f"[WhatsApp Web] Send button clicked with selector: {selector}")
                        break
                except Exception:
                    continue

            # Fallback: Press Enter key if no send button was clicked
            if not send_clicked:
                logger.info("[WhatsApp Web] Send button not found, using Enter key fallback")
                # Find the message input and press Enter
                input_selectors = [
                    '[data-testid="conversation-compose-box-input"]',
                    'div[contenteditable="true"][data-tab="10"]',
                    'div[contenteditable="true"][role="textbox"]',
                    'footer div[contenteditable="true"]',
                    '#main footer div[contenteditable="true"]'
                ]

                for selector in input_selectors:
                    try:
                        input_box = page.locator(selector)
                        if await input_box.count() > 0:
                            # Ensure focused and press Enter
                            await input_box.first.click()
                            await input_box.first.press('Enter')
                            send_clicked = True
                            logger.info(f"[WhatsApp Web] Sent via Enter key on input: {selector}")
                            break
                    except Exception:
                        continue

            if send_clicked:
                session.last_activity = datetime.utcnow()
                # Wait a moment for message to be sent
                await asyncio.sleep(2)
                return {
                    "success": True,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            
            # If still failed, try manual fill and send (URL param might have failed)
            logger.info("[WhatsApp Web] Trying manual fill fallback")
            input_selectors = [
                'div[contenteditable="true"][data-tab="10"]',
                'div[contenteditable="true"][role="textbox"]',
                'footer div[contenteditable="true"]'
            ]
            for selector in input_selectors:
                try:
                    input_box = page.locator(selector)
                    if await input_box.count() > 0:
                        await input_box.first.fill(message)
                        await asyncio.sleep(0.5)
                        await input_box.first.press('Enter')
                        session.last_activity = datetime.utcnow()
                        return {"success": True, "timestamp": datetime.utcnow().isoformat(), "note": "manual_fill"}
                except Exception:
                    continue

            return {"success": False, "error": "Could not send message - no send button or input field found"}

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to send message: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def send_media(
        self,
        session_id: str,
        to: str,
        media_path: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send media (image, video, document) via WhatsApp Web.

        Args:
            session_id: The session ID to use
            to: Recipient phone number
            media_path: Path to the media file
            caption: Optional caption for the media

        Returns:
            Dict with message ID and status
        """
        page = self._pages.get(session_id)
        session = self._sessions.get(session_id)

        if not page or not session or session.status != "connected":
            return {"success": False, "error": "Session not connected"}

        try:
            # Clean phone number
            phone = to.lstrip('+').replace(' ', '').replace('-', '')

            # Navigate to chat
            await page.goto(f'https://web.whatsapp.com/send?phone={phone}')
            await page.wait_for_load_state('networkidle')
            await asyncio.sleep(3)

            # Try multiple selectors for the attach button
            attach_selectors = [
                '[data-testid="attach-menu-plus"]',
                '[data-icon="attach-menu-plus"]',
                '[data-icon="plus"]',
                '[data-testid="clip"]',
                '[data-icon="clip"]',
                'button[aria-label="Attach"]',
                '[aria-label="Attach"]',
                'span[data-icon="attach-menu-plus"]',
                'span[data-icon="plus"]',
            ]

            attach_clicked = False
            for selector in attach_selectors:
                try:
                    attach_btn = page.locator(selector)
                    if await attach_btn.count() > 0:
                        await attach_btn.first.click()
                        attach_clicked = True
                        logger.info(f"[WhatsApp Web] Attach button clicked with selector: {selector}")
                        break
                except Exception:
                    continue

            if not attach_clicked:
                return {"success": False, "error": "Could not find attach button"}

            await asyncio.sleep(1)

            # Upload file
            file_input = page.locator('input[type="file"]')
            if await file_input.count() == 0:
                return {"success": False, "error": "Could not find file input"}

            await file_input.set_input_files(media_path)
            await asyncio.sleep(3)

            # Add caption if provided
            if caption:
                caption_selectors = [
                    '[data-testid="media-caption-input-container"] [contenteditable="true"]',
                    'div[data-testid="media-caption-text-input"]',
                    '[aria-label="Add a caption"]',
                    'div[contenteditable="true"][data-tab="6"]',
                ]
                for selector in caption_selectors:
                    try:
                        caption_input = page.locator(selector)
                        if await caption_input.count() > 0:
                            await caption_input.first.fill(caption)
                            logger.info(f"[WhatsApp Web] Caption added with selector: {selector}")
                            break
                    except Exception:
                        continue

            # Try multiple selectors for the send button
            send_selectors = [
                '[data-testid="send"]',
                '[data-icon="send"]',
                'button[aria-label="Send"]',
                'span[data-icon="send"]',
                '[aria-label="Send"]',
                'button:has(span[data-icon="send"])',
            ]

            send_clicked = False
            for selector in send_selectors:
                try:
                    send_btn = page.locator(selector)
                    if await send_btn.count() > 0:
                        await send_btn.first.click()
                        send_clicked = True
                        logger.info(f"[WhatsApp Web] Media send button clicked with selector: {selector}")
                        break
                except Exception:
                    continue

            if send_clicked:
                session.last_activity = datetime.utcnow()
                await asyncio.sleep(1)
                return {
                    "success": True,
                    "timestamp": datetime.utcnow().isoformat(),
                }

            return {"success": False, "error": "Could not find send button after attaching media"}

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to send media: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_chat_messages(
        self,
        session_id: str,
        phone_number: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Get recent messages from a specific chat.

        Args:
            session_id: The session ID
            phone_number: The phone number to get messages from
            limit: Maximum number of messages to retrieve (default 50)

        Returns:
            Dict with success status and list of messages
        """
        page = self._pages.get(session_id)
        session = self._sessions.get(session_id)

        if not page or not session or session.status != "connected":
            return {"success": False, "error": "Session not connected"}

        try:
            # Clean phone number
            phone = phone_number.lstrip('+').replace(' ', '').replace('-', '')

            # Navigate to chat
            await page.goto(f'https://web.whatsapp.com/send?phone={phone}')
            await page.wait_for_load_state('networkidle')
            await asyncio.sleep(5)  # Wait for chat history to load

            # Check for invalid number popup
            popup = page.locator('div[data-testid="popup-controls-ok"]')
            if await popup.count() > 0:
                await popup.click()
                return {"success": False, "error": "Invalid phone number"}

            # Get messages
            # Select all message rows
            message_rows = page.locator('div[role="row"]')
            
            # Wait for at least one message or timeout (new chat might be empty)
            try:
                await message_rows.first.wait_for(timeout=5000)
            except:
                pass # Might be empty chat

            count = await message_rows.count()
            logger.info(f"[WhatsApp Web] Found {count} messages in chat")

            messages = []
            # Calculate start index to get only the last 'limit' messages
            start_idx = max(0, count - limit)
            
            for i in range(start_idx, count):
                try:
                    row = message_rows.nth(i)
                    
                    # Determine if incoming or outgoing
                    is_outgoing = await row.locator('.message-out').count() > 0
                    
                    # 1. Try to get text from span.selectable-text (most common for text msgs)
                    text_elems = row.locator('span.selectable-text')
                    text = ""
                    if await text_elems.count() > 0:
                        # Collect all text parts
                        text_parts = []
                        for j in range(await text_elems.count()):
                             # Filter out empty spans
                             t = await text_elems.nth(j).inner_text()
                             if t.strip():
                                 text_parts.append(t)
                        text = "\n".join(text_parts)
                    
                    # 2. If no text, check for specific media indicators
                    if not text:
                        # Check for video
                        if await row.locator('video').count() > 0:
                            text = "[Video]"
                        # Check for image (exclude profile pics/emojis which are small)
                        # We look for img tags that are likely content
                        elif await row.locator('img[src*="blob:"]').count() > 0:
                             text = "[Image]"
                        
                        # Only label as generic media if we really can't find text and it seems to contain visual elements
                        elif await row.locator('div[data-testid="media-msg"]').count() > 0:
                             text = "[Media]"

                    # 3. Timestamp/Sender from metadata
                    timestamp = ""
                    sender = "them"
                    if is_outgoing:
                        sender = "me"
                    
                    # The container with class 'copyable-text' has data-pre-plain-text
                    copyable = row.locator('div.copyable-text').first
                    if await copyable.count() > 0:
                        data_pre = await copyable.get_attribute('data-pre-plain-text')
                        if data_pre:
                            # Clean up the format: "[10:30, 02/02/2026] Name: "
                            timestamp = data_pre.split(']')[0].replace('[', '').strip()
                            if not is_outgoing:
                                parts = data_pre.split(']')
                                if len(parts) > 1:
                                    sender = parts[1].strip().rstrip(':')

                    # Final check: if text is empty and it's not explicitly media, try to grab *any* text as fallback
                    # This catches system messages or weirdly formatted text
                    if not text and not text.startswith("["):
                        try:
                            # Try getting all text from the row, excluding time
                            all_text = await row.inner_text()
                            lines = all_text.split('\n')
                            if lines:
                                # First line is often the content if it's not empty
                                candidate = lines[0].strip()
                                if candidate and candidate != timestamp and candidate != sender:
                                    text = candidate
                        except Exception:
                            pass

                    messages.append({
                        "text": text,
                        "is_outgoing": is_outgoing,
                        "timestamp": timestamp,
                        "sender": sender
                    })
                except Exception as e:
                    logger.debug(f"[WhatsApp Web] Error parsing message row {i}: {e}")
                    continue

            return {
                "success": True, 
                "messages": messages,
                "count": len(messages),
                "chat": phone_number
            }

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to get messages: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_chat_messages_by_name(
        self,
        session_id: str,
        chat_name: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Open a chat by clicking on it in the sidebar and read its messages.

        Unlike get_chat_messages (which navigates via phone URL), this method
        clicks the chat entry in the sidebar by name.  This is suitable for
        the polling loop where we already know the chat name from
        get_unread_chats.

        Returns:
            Dict with success status and list of messages
        """
        page = self._pages.get(session_id)
        session = self._sessions.get(session_id)

        if not page or not session or session.status != "connected":
            return {"success": False, "error": "Session not connected"}

        try:
            # Find the chat in the sidebar by its title/name
            chat_item = page.locator(f'span[title="{chat_name}"]').first
            if await chat_item.count() == 0:
                # Try a more relaxed match (contains)
                chat_item = page.locator(f'span[title*="{chat_name}"]').first
                if await chat_item.count() == 0:
                    return {"success": False, "error": f"Chat '{chat_name}' not found in sidebar"}

            # Click on the chat to open it
            await chat_item.click()
            await asyncio.sleep(2)  # Wait for chat to load

            # Read messages from the open chat (reuse the same scraping logic)
            message_rows = page.locator('div[role="row"]')
            try:
                await message_rows.first.wait_for(timeout=5000)
            except Exception:
                pass  # Might be empty chat

            count = await message_rows.count()
            messages = []
            start_idx = max(0, count - limit)

            for i in range(start_idx, count):
                try:
                    row = message_rows.nth(i)

                    is_outgoing = await row.locator('.message-out').count() > 0

                    text_elems = row.locator('span.selectable-text')
                    text = ""
                    if await text_elems.count() > 0:
                        text_parts = []
                        for j in range(await text_elems.count()):
                            t = await text_elems.nth(j).inner_text()
                            if t.strip():
                                text_parts.append(t)
                        text = "\n".join(text_parts)

                    if not text:
                        if await row.locator('video').count() > 0:
                            text = "[Video]"
                        elif await row.locator('img[src*="blob:"]').count() > 0:
                            text = "[Image]"
                        elif await row.locator('div[data-testid="media-msg"]').count() > 0:
                            text = "[Media]"

                    timestamp = ""
                    sender = "them"
                    if is_outgoing:
                        sender = "me"

                    copyable = row.locator('div.copyable-text').first
                    if await copyable.count() > 0:
                        data_pre = await copyable.get_attribute('data-pre-plain-text')
                        if data_pre:
                            timestamp = data_pre.split(']')[0].replace('[', '').strip()
                            if not is_outgoing:
                                parts = data_pre.split(']')
                                if len(parts) > 1:
                                    sender = parts[1].strip().rstrip(':')

                    if not text and not text.startswith("["):
                        try:
                            all_text = await row.inner_text()
                            lines = all_text.split('\n')
                            if lines:
                                candidate = lines[0].strip()
                                if candidate and candidate != timestamp and candidate != sender:
                                    text = candidate
                        except Exception:
                            pass

                    messages.append({
                        "text": text,
                        "is_outgoing": is_outgoing,
                        "timestamp": timestamp,
                        "sender": sender,
                    })
                except Exception as e:
                    logger.debug(f"[WhatsApp Web] Error parsing message row {i}: {e}")
                    continue

            return {
                "success": True,
                "messages": messages,
                "count": len(messages),
                "chat": chat_name,
            }

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to get messages by name for '{chat_name}': {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_own_profile_name(
        self,
        session_id: str,
    ) -> Optional[str]:
        """Return the logged-in user's own WhatsApp display name, or *None*."""
        page = self._pages.get(session_id)
        session = self._sessions.get(session_id)
        if not page or not session or session.status != "connected":
            return None
        try:
            name = await page.evaluate("""() => {
                // The profile avatar button at the top-left of the sidebar
                // contains a clickable img whose alt text is the user's name.
                const avatar = document.querySelector(
                    'header img[alt]'
                );
                if (avatar) {
                    const alt = avatar.getAttribute('alt');
                    if (alt && alt.length > 0) return alt;
                }
                // Fallback: the header span with the user's name
                const headerSpan = document.querySelector(
                    'header span[title]'
                );
                if (headerSpan) return headerSpan.getAttribute('title') || '';
                return '';
            }""")
            return name if name else None
        except Exception as e:
            logger.debug(f"[WhatsApp Web] Could not read own profile name: {e}")
            return None

    async def get_unread_chats(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Get a list of chats that have unread messages.
        
        Returns:
            Dict with list of unread chats (names/numbers and unread counts)
        """
        page = self._pages.get(session_id)
        session = self._sessions.get(session_id)

        if not page or not session or session.status != "connected":
            return {"success": False, "error": "Session not connected"}

        try:
            # Use JavaScript to extract chat data from the sidebar.
            # We collect: name, badge count, and a stable preview fingerprint
            # built from ALL text inside the row (minus the name and timestamp).
            chat_data = await page.evaluate("""() => {
                const rows = document.querySelectorAll('#pane-side div[role="row"]');
                const seen = new Set();
                const results = [];
                for (const row of rows) {
                    // 1. Chat name: first span[title] in the row
                    const nameEl = row.querySelector('span[title]');
                    if (!nameEl) continue;
                    const name = nameEl.getAttribute('title') || nameEl.textContent || '';
                    if (!name || seen.has(name)) continue;
                    seen.add(name);

                    // 2. Unread badge: find a small span with only digits
                    //    and a colored background (the green unread circle)
                    let unreadCount = 0;
                    const allSpans = row.querySelectorAll('span');
                    for (const sp of allSpans) {
                        const txt = sp.textContent.trim();
                        if (/^\\d{1,4}$/.test(txt) && sp !== nameEl) {
                            const rect = sp.getBoundingClientRect();
                            if (rect.width > 0 && rect.width < 40 && rect.height < 30) {
                                const el = sp.closest('[style]') || sp.parentElement;
                                const style = window.getComputedStyle(el || sp);
                                const bg = style.backgroundColor;
                                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                                    unreadCount = parseInt(txt, 10);
                                    break;
                                }
                            }
                        }
                    }

                    // 3. Muted: WhatsApp Web shows a muted speaker icon
                    const isMuted = row.querySelector('span[data-icon="muted"]') !== null
                        || row.querySelector('[data-testid="muted"]') !== null;

                    // 4. Group detection (best-effort from sidebar):
                    //    a) Groups without a custom photo use the default-group icon
                    //    b) Group preview text shows "Sender: message" format
                    let isGroup = row.querySelector('span[data-icon="default-group"]') !== null;
                    if (!isGroup) {
                        const fullInner = row.innerText || '';
                        const lines = fullInner.split('\\n').map(l => l.trim()).filter(Boolean);
                        // Skip first line (chat name) and look for "Name: text" pattern in preview
                        for (let k = 1; k < lines.length; k++) {
                            const line = lines[k];
                            // Match "SenderName: preview" but exclude timestamps (e.g. "12:30")
                            // and URLs (e.g. "https://...")
                            if (/^[^:]{1,30}:\\s/.test(line)
                                && !/^\\d{1,2}:\\d{2}/.test(line)
                                && !line.startsWith('http')) {
                                isGroup = true;
                                break;
                            }
                        }
                    }

                    // 5. Stable preview: get the full inner text of the row,
                    //    strip the chat name from the start.  This captures
                    //    the preview snippet + timestamp as a single string
                    //    that only changes when the chat actually updates.
                    const fullText = row.innerText.trim();

                    results.push({
                        name: name,
                        unread_count: unreadCount,
                        is_muted: isMuted,
                        is_group: isGroup,
                        full_text: fullText.substring(0, 300),
                    });
                }
                return results;
            }""")

            if not chat_data:
                return {"success": True, "unread_chats": [], "count": 0}

            # Log sample once for debugging
            if not hasattr(self, '_first_poll_logged'):
                self._first_poll_logged = True
                sample = chat_data[:5]
                logger.info(f"[WhatsApp Web] Sample chat rows ({len(chat_data)} total): {sample}")

            unread_chats = []

            for chat in chat_data:
                name = chat.get("name", "")
                badge_count = chat.get("unread_count", 0)
                full_text = chat.get("full_text", "")

                if not name:
                    continue

                # Method 1: Has an unread badge (works for others' messages)
                if badge_count > 0:
                    unread_chats.append({
                        "name": name,
                        "unread_count": str(badge_count),
                        "source": "badge",
                    })
                    self._chat_previews[name] = full_text
                    continue

                # Method 2: Full text fingerprint changed
                # (catches self-messages and any case without badges)
                old_text = self._chat_previews.get(name)
                if old_text is not None and full_text and full_text != old_text:
                    logger.info(f"[WhatsApp Web] Chat changed: '{name}'")
                    unread_chats.append({
                        "name": name,
                        "unread_count": "1",
                        "source": "preview_change",
                    })

                if full_text:
                    self._chat_previews[name] = full_text

            if unread_chats:
                logger.info(f"[WhatsApp Web] Chats with activity: {[(c['name'], c['unread_count']) for c in unread_chats]}")

            return {
                "success": True,
                "unread_chats": unread_chats,
                "count": len(unread_chats)
            }

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to get unread chats: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def resolve_contact_phone(
        self,
        session_id: str,
        name: str,
    ) -> Dict[str, Any]:
        """
        Resolve a contact name to a phone number using fuzzy matching.

        This function searches for contacts and uses fuzzy matching to find the best match.
        For example, "Emad Tavana" will match "Emad Tavana MDX" but NOT "Emad Davane".
        """
        page = self._pages.get(session_id)
        session = self._sessions.get(session_id)

        if not page or not session or session.status != "connected":
            return {"success": False, "error": "Session not connected"}

        try:
            # Clear any previous search
            # Try multiple selectors for search bar
            search_selectors = [
                'div[contenteditable="true"][data-tab="3"]',
                '[data-testid="chat-list-search"]',
                '[aria-label="Search or start new chat"]',
                '[title="Search input textbox"]'
            ]

            search_box = None
            for selector in search_selectors:
                if await page.locator(selector).count() > 0:
                    search_box = page.locator(selector).first
                    break

            if not search_box:
                return {"success": False, "error": "Could not find search bar"}

            await search_box.click()
            await search_box.fill("")
            await asyncio.sleep(0.5)

            logger.info(f"[WhatsApp Web] Searching for contact: '{name}'")
            await search_box.fill(name)

            # Wait for results
            await asyncio.sleep(2)

            # Use span[title] elements directly since they reliably contain contact names
            # The container selectors change frequently, but span[title] is stable
            all_titles = page.locator('#pane-side span[title]')
            title_count = await all_titles.count()

            logger.info(f"[WhatsApp Web] Found {title_count} span[title] elements in side pane")

            if title_count == 0:
                await asyncio.sleep(2)
                title_count = await all_titles.count()
                logger.info(f"[WhatsApp Web] After retry: {title_count} span[title] elements")

            if title_count == 0:
                return {"success": False, "error": f"No contacts visible on page for '{name}'"}

            # Collect all visible contact names and find the best fuzzy match
            best_match_elem = None
            best_match_score = 0.0
            best_match_name = ""
            candidates = []
            seen_names = set()  # Avoid duplicates

            for i in range(min(title_count, 30)):  # Check up to 30 results
                try:
                    title_elem = all_titles.nth(i)
                    contact_name = await title_elem.get_attribute('title')

                    if not contact_name or len(contact_name) < 2:
                        continue

                    # Skip duplicates and system messages
                    if contact_name in seen_names:
                        continue
                    seen_names.add(contact_name)

                    # Skip obvious non-contact entries (system messages, etc.)
                    if contact_name.startswith('\u202a') or 'also in this group' in contact_name.lower():
                        continue

                    is_match, score = _fuzzy_name_match(name, contact_name)
                    candidates.append({"name": contact_name, "score": score, "is_match": is_match, "elem": title_elem})
                    logger.debug(f"[WhatsApp Web] Contact candidate: '{contact_name}' - score: {score:.2f}, match: {is_match}")

                    if is_match and score > best_match_score:
                        best_match_score = score
                        best_match_elem = title_elem
                        best_match_name = contact_name
                except Exception as e:
                    logger.debug(f"[WhatsApp Web] Error checking title {i}: {e}")
                    continue

            if best_match_elem is None:
                # No good fuzzy match found
                candidate_names = [c["name"] for c in candidates[:5] if c.get("name")]
                logger.info(f"[WhatsApp Web] No fuzzy match for '{name}'. Candidates: {candidate_names}")
                return {
                    "success": False,
                    "error": f"No contact found matching '{name}'. Similar contacts: {', '.join(candidate_names) if candidate_names else 'none'}"
                }

            logger.info(f"[WhatsApp Web] Best fuzzy match for '{name}': '{best_match_name}' (score: {best_match_score:.2f})")

            # Click the best matching result (click the span element itself)
            await best_match_elem.click()

            # Wait for chat to load
            await asyncio.sleep(2)

            # Click header to open info - the clickable area in WhatsApp Web is usually a div containing the contact info
            # We need to find the right clickable area that opens the contact drawer

            # First, let's try clicking the header section that contains contact info
            # WhatsApp Web typically has a clickable section with the contact name and status
            header_click_attempts = [
                # Try clicking the conversation panel header (the whole clickable area)
                ('#main header [data-testid="conversation-panel-header"]', 'conversation-panel-header'),
                # Try the section containing avatar and name
                ('#main header section', 'header section'),
                # Try clicking the div containing the title
                ('#main header div[title]', 'header div with title'),
                # The contact name span's parent (usually a clickable div)
                ('#main header span[title]', 'span title (then parent)'),
                # Avatar in header
                ('#main header [data-testid="avatar"]', 'avatar'),
                ('#main header img[draggable="false"]', 'avatar img'),
                # The whole header as last resort
                ('#main header', 'whole header'),
            ]

            clicked = False
            for sel, desc in header_click_attempts:
                try:
                    elem = page.locator(sel).first
                    if await elem.count() > 0:
                        logger.debug(f"[WhatsApp Web] Trying to click: {desc} ({sel})")

                        # For span[title], try clicking its parent instead
                        if 'span[title]' in sel:
                            # Get bounding box and click in the center area of the header
                            box = await elem.bounding_box()
                            if box:
                                # Click slightly to the left of the span (in the avatar/name area)
                                await page.mouse.click(box['x'] - 50, box['y'] + box['height'] / 2)
                                logger.debug(f"[WhatsApp Web] Clicked near span title at x={box['x']-50}")
                                clicked = True
                                break
                        else:
                            await elem.click(force=True)
                            clicked = True
                            logger.debug(f"[WhatsApp Web] Clicked: {desc}")
                            break
                except Exception as e:
                    logger.debug(f"[WhatsApp Web] Failed to click {desc}: {e}")
                    continue

            if not clicked:
                logger.warning("[WhatsApp Web] Could not find/click chat header")
                return {"success": False, "error": "Could not find chat header"}

            # Wait for panel to open
            await asyncio.sleep(3)

            # Check if any new panel appeared by looking for common drawer elements
            logger.debug("[WhatsApp Web] Checking for opened panel...")

            # Look for phone in sidebar (right side) - try multiple selectors
            side_panel_selectors = [
                'div[data-testid="contact-info-drawer"]',
                'div[data-testid="group-info-drawer"]',
                'div[data-testid="chat-info-drawer"]',
                '[data-testid="contact-info-drawer"]',
                '#app div[tabindex="-1"][data-animate-modal-popup="true"]',
                'section[data-testid="contact-info"]',
                # Try any drawer/panel that appeared
                'div[data-animate-drawer="true"]',
                'div[style*="transform: translateX(0"]',  # Visible drawer
                '#app > div > div > div:nth-child(3)',  # Third column (right panel)
            ]

            side_panel = None
            for sel in side_panel_selectors:
                try:
                    loc = page.locator(sel)
                    cnt = await loc.count()
                    if cnt > 0:
                        side_panel = loc.first
                        logger.debug(f"[WhatsApp Web] Found side panel with selector: {sel} (count: {cnt})")
                        break
                except Exception:
                    continue

            # Debug: Log all divs with data-testid to see what's available
            if not side_panel:
                try:
                    testids = page.locator('[data-testid]')
                    testid_count = await testids.count()
                    testid_names = []
                    for i in range(min(testid_count, 30)):
                        try:
                            tid = await testids.nth(i).get_attribute('data-testid')
                            if tid and 'drawer' in tid.lower() or 'info' in tid.lower() or 'panel' in tid.lower():
                                testid_names.append(tid)
                        except Exception:
                            pass
                    if testid_names:
                        logger.debug(f"[WhatsApp Web] Available data-testid with drawer/info/panel: {testid_names}")
                except Exception:
                    pass

            phone = None
            panel_text = ""

            # If we found a side panel with specific selectors, use it
            if side_panel:
                try:
                    panel_text = await side_panel.inner_text()
                    logger.debug(f"[WhatsApp Web] Side panel text (first 300 chars): {panel_text[:300]}")
                except Exception as e:
                    logger.warning(f"[WhatsApp Web] Error getting side panel text: {e}")

            # If no specific panel found, try to find the contact info section
            # by looking for the panel that opened (contains "Close" button)
            if not panel_text or panel_text == "Close":
                logger.debug("[WhatsApp Web] Trying alternative panel detection...")
                try:
                    # Find the close button and get content from its sibling/parent
                    close_btn = page.locator('[aria-label="Close"], [data-testid="x"], [data-icon="x"]').first
                    if await close_btn.count() > 0:
                        # Get the parent container of the close button (usually the drawer)
                        # Try to get all text from the page's right section
                        # WhatsApp structure: #app > div > div > div (left) + div (center/main) + div (right panel)
                        all_divs = page.locator('#app > div > div > div')
                        div_count = await all_divs.count()
                        logger.debug(f"[WhatsApp Web] Found {div_count} main divs in app")

                        # The rightmost div (if 3 exist) should be the info panel
                        if div_count >= 3:
                            right_panel = all_divs.nth(2)  # 0-indexed, so 2 is the third
                            panel_text = await right_panel.inner_text()
                            logger.debug(f"[WhatsApp Web] Right panel (div 2) text (first 500 chars): {panel_text[:500]}")
                except Exception as e:
                    logger.debug(f"[WhatsApp Web] Alternative panel detection failed: {e}")

            # Now search for phone number in the panel text
            if panel_text and len(panel_text) > 10:
                # Pattern 1: International format +1 234 567 8900 or +44 7xxx
                phones = re.findall(r'\+\d[\d\s-]{7,}', panel_text)
                if phones:
                    phone = phones[0].strip().replace(" ", "").replace("-", "")
                    logger.debug(f"[WhatsApp Web] Found phone (pattern 1): {phone}")

                # Pattern 2: Phone with country code but no + (like "44 7911 123456")
                if not phone:
                    # Look for sequences that look like phone numbers
                    phone_candidates = re.findall(r'(?<!\d)(\d{10,15})(?!\d)', panel_text.replace(" ", "").replace("-", ""))
                    if phone_candidates:
                        phone = "+" + phone_candidates[0]
                        logger.debug(f"[WhatsApp Web] Found phone (pattern 2): {phone}")

            # If still no phone from text, try span elements directly on the page
            if not phone:
                try:
                    # Look for any span on page with phone number in title or text
                    phone_spans = page.locator('span[title*="+"]')
                    span_count = await phone_spans.count()
                    logger.debug(f"[WhatsApp Web] Found {span_count} spans with + in title")
                    for i in range(min(span_count, 20)):
                        try:
                            title = await phone_spans.nth(i).get_attribute('title')
                            if title and re.match(r'^\+\d[\d\s-]{7,}$', title.strip()):
                                phone = title.strip().replace(" ", "").replace("-", "")
                                logger.debug(f"[WhatsApp Web] Found phone from span title: {phone}")
                                break
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"[WhatsApp Web] Span search failed: {e}")

            # Close info drawer
            close_btn = page.locator('[data-testid="x"], [data-icon="x"], [aria-label="Close"]')
            if await close_btn.count() > 0:
                try:
                    await close_btn.first.click()
                except Exception:
                    pass

            if phone:
                return {"success": True, "name": best_match_name, "phone": phone}
            else:
                # Fallback: if user provided a name that IS the phone number
                if name.replace("+", "").replace(" ", "").isdigit():
                    return {"success": True, "name": name, "phone": name}

                return {
                    "success": False,
                    "error": f"Contact '{best_match_name}' found but could not extract phone number from profile",
                    "debug": {
                        "panel_text_preview": panel_text[:200] if panel_text else "no panel text"
                    }
                }

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to resolve contact: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def export_session_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Export session data (cookies, localStorage) for a connected session.

        This allows the session to be transferred to another agent.
        Note: WhatsApp Web stores session keys in IndexedDB which may not be
        fully captured - the receiving agent may need to re-authenticate.

        Returns:
            Dict with storage_state (cookies, localStorage) or None if session not found
        """
        if session_id not in self._browsers:
            logger.warning(f"[WhatsApp Web] Cannot export session {session_id}: no active browser")
            return None

        session = self._sessions.get(session_id)
        if not session or session.status != "connected":
            logger.warning(f"[WhatsApp Web] Cannot export session {session_id}: not connected")
            return None

        try:
            playwright, browser = self._browsers[session_id]
            # Export storage state (cookies and localStorage)
            storage_state = await browser.storage_state()

            logger.info(f"[WhatsApp Web] Exported session data for {session_id}")
            return {
                "storage_state": storage_state,
                "jid": session.jid,
                "phone_number": session.phone_number,
            }
        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to export session data for {session_id}: {e}")
            return None

    async def restore_session_from_data(
        self,
        session_id: str,
        user_id: str,
        session_data: Dict[str, Any],
        on_connected: Optional[Callable[[str, str], None]] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """
        Restore a WhatsApp Web session from exported session data.

        This is used when receiving credentials from another agent.

        Args:
            session_id: Session identifier
            user_id: User ID to associate
            session_data: Exported session data containing storage_state
            on_connected: Callback when connected
            on_disconnected: Callback when disconnected

        Returns:
            Dict with status and session info
        """
        if session_id in self._sessions:
            session = self._sessions[session_id]
            return {
                "success": True,
                "status": session.status,
                "session_id": session_id,
                "message": "Session already active"
            }

        storage_state = session_data.get("storage_state")
        if not storage_state:
            return {
                "success": False,
                "error": "No storage_state in session_data"
            }

        try:
            from playwright.async_api import async_playwright

            logger.info(f"[WhatsApp Web] Restoring session {session_id} from session data")

            # Create session object
            session = WhatsAppWebSession(
                session_id=session_id,
                user_id=user_id,
                status="restoring",
                jid=session_data.get("jid"),
                phone_number=session_data.get("phone_number"),
                created_at=datetime.utcnow(),
            )
            self._sessions[session_id] = session

            # Get or create session directory for persistent context
            session_path = self._get_session_path(session_id)
            session_path.mkdir(parents=True, exist_ok=True)

            # Launch browser with persistent context
            playwright = await async_playwright().start()
            self._playwright_loop = asyncio.get_running_loop()
            browser = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(session_path),
                headless=True,
                storage_state=storage_state,  # Inject the storage state
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',
                ],
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
                locale='en-US',
            )

            self._browsers[session_id] = (playwright, browser)

            # Get page
            pages = browser.pages
            if pages:
                page = pages[0]
            else:
                page = await browser.new_page()
            self._pages[session_id] = page

            # Navigate to WhatsApp Web
            logger.info(f"[WhatsApp Web] Navigating to WhatsApp Web for restored session...")
            await page.goto('https://web.whatsapp.com', wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_load_state('networkidle', timeout=30000)

            # Wait for page to stabilize
            await asyncio.sleep(3)

            # Check if logged in
            logged_in_selectors = [
                '[data-testid="chat-list"]',
                'div[data-tab="3"]',
                '#side',
            ]

            is_logged_in = False
            for selector in logged_in_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        is_logged_in = True
                        break
                except Exception:
                    continue

            if is_logged_in:
                session.status = "connected"
                session.last_activity = datetime.utcnow()
                logger.info(f"[WhatsApp Web] Session {session_id} restored successfully!")

                if on_connected:
                    on_connected(session.jid or "", session.phone_number or "")

                return {
                    "success": True,
                    "status": "connected",
                    "session_id": session_id,
                    "jid": session.jid,
                    "phone_number": session.phone_number,
                    "message": "Successfully restored WhatsApp Web session"
                }
            else:
                # Check if QR code is shown
                qr_selectors = [
                    'canvas[aria-label="Scan this QR code to link a device!"]',
                    'canvas[aria-label*="QR"]',
                    '[data-testid="qrcode"]',
                ]

                needs_qr = False
                for selector in qr_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            needs_qr = True
                            break
                    except Exception:
                        continue

                if needs_qr:
                    session.status = "qr_required"
                    logger.warning(f"[WhatsApp Web] Restored session {session_id} requires new QR scan")
                    return {
                        "success": False,
                        "status": "qr_required",
                        "session_id": session_id,
                        "error": "Session data was transferred but WhatsApp requires re-authentication.",
                        "hint": "The session may have expired. Start a new session and scan the QR code."
                    }
                else:
                    session.status = "unknown"
                    return {
                        "success": False,
                        "status": "unknown",
                        "session_id": session_id,
                        "error": "Could not determine session state after restore."
                    }

        except ImportError as e:
            logger.error(f"[WhatsApp Web] Playwright not installed: {e}")
            return {"success": False, "error": "Playwright not installed"}

        except Exception as e:
            logger.error(f"[WhatsApp Web] Failed to restore session: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


# Global manager instance
_manager: Optional[WhatsAppWebManager] = None


def get_whatsapp_web_manager() -> WhatsAppWebManager:
    """Get the global WhatsApp Web manager instance."""
    global _manager
    if _manager is None:
        _manager = WhatsAppWebManager()
    return _manager


# Convenience functions for direct use

async def start_whatsapp_web_session(
    user_id: str,
    session_id: Optional[str] = None,
) -> WhatsAppWebSession:
    """Start a new WhatsApp Web session and get QR code."""
    manager = get_whatsapp_web_manager()
    return await manager.create_session(user_id, session_id)


async def get_session_status(session_id: str, include_session_data: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get the current status of a WhatsApp Web session.

    Args:
        session_id: The session ID to check
        include_session_data: If True and session is connected, include exportable session data
    """
    manager = get_whatsapp_web_manager()
    session = manager.get_session(session_id)
    if not session:
        return None

    result = {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "status": session.status,
        "qr_code": session.qr_code,
        "phone_number": session.phone_number,
        "jid": session.jid,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }

    # Include session data for backend storage when connected
    if include_session_data and session.status == "connected":
        session_data = await manager.export_session_data(session_id)
        if session_data:
            result["session_data"] = session_data

    return result


async def export_whatsapp_web_session_data(session_id: str) -> Optional[Dict[str, Any]]:
    """Export session data for a connected WhatsApp Web session."""
    manager = get_whatsapp_web_manager()
    return await manager.export_session_data(session_id)


async def restore_whatsapp_web_session(
    session_id: str,
    user_id: str,
    session_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Restore a WhatsApp Web session from exported session data.

    This is used when receiving credentials from another agent.
    """
    manager = get_whatsapp_web_manager()
    return await manager.restore_session_from_data(session_id, user_id, session_data)


async def send_whatsapp_web_message(
    session_id: str,
    to: str,
    message: str,
) -> Dict[str, Any]:
    """Send a message via WhatsApp Web."""
    manager = get_whatsapp_web_manager()
    return await manager.run_on_playwright_loop(
        manager.send_message(session_id, to, message)
    )


async def disconnect_whatsapp_web_session(session_id: str) -> bool:
    """Disconnect a WhatsApp Web session."""
    manager = get_whatsapp_web_manager()
    return await manager.disconnect_session(session_id)


async def send_whatsapp_web_media(
    session_id: str,
    to: str,
    media_path: str,
    caption: Optional[str] = None,
) -> Dict[str, Any]:
    """Send media via WhatsApp Web."""
    manager = get_whatsapp_web_manager()
    return await manager.run_on_playwright_loop(
        manager.send_media(session_id, to, media_path, caption)
    )


async def reconnect_whatsapp_web_session(
    session_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """
    Reconnect to an existing WhatsApp Web session using persisted browser data.

    Use this after agent restart when the session data exists on disk
    but the browser is no longer running.
    """
    manager = get_whatsapp_web_manager()
    return await manager.reconnect_session(session_id, user_id)


def list_persisted_whatsapp_web_sessions() -> List[Dict[str, Any]]:
    """
    List all WhatsApp Web sessions that have persisted data on disk.

    These sessions can potentially be reconnected without a new QR scan
    if the device is still linked on the phone.
    """
    manager = get_whatsapp_web_manager()
    return manager.list_persisted_sessions()


async def get_whatsapp_web_chat_messages(
    session_id: str,
    phone_number: str,
    limit: int = 50,
) -> Dict[str, Any]:
    """Get recent messages from a specific chat via WhatsApp Web."""
    manager = get_whatsapp_web_manager()
    return await manager.run_on_playwright_loop(
        manager.get_chat_messages(session_id, phone_number, limit)
    )


async def get_whatsapp_web_chat_messages_by_name(
    session_id: str,
    chat_name: str,
    limit: int = 50,
) -> Dict[str, Any]:
    """Get recent messages from a chat by clicking it in the sidebar (by name)."""
    manager = get_whatsapp_web_manager()
    return await manager.run_on_playwright_loop(
        manager.get_chat_messages_by_name(session_id, chat_name, limit)
    )


async def get_whatsapp_web_unread_chats(
    session_id: str,
) -> Dict[str, Any]:
    """Get a list of chats that have unread messages via WhatsApp Web."""
    manager = get_whatsapp_web_manager()
    return await manager.run_on_playwright_loop(
        manager.get_unread_chats(session_id)
    )


async def get_whatsapp_web_own_profile_name(
    session_id: str,
) -> Optional[str]:
    """Return the logged-in user's own WhatsApp display name, or *None*."""
    manager = get_whatsapp_web_manager()
    return await manager.run_on_playwright_loop(
        manager.get_own_profile_name(session_id)
    )


async def get_whatsapp_web_contact_phone(
    session_id: str,
    contact_name: str,
) -> Dict[str, Any]:
    """Resolve a contact name to a phone number via WhatsApp Web."""
    manager = get_whatsapp_web_manager()
    return await manager.run_on_playwright_loop(
        manager.resolve_contact_phone(session_id, contact_name)
    )
