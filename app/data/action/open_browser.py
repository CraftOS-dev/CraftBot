from agent_core import action

@action(
    name="open_browser",
    description="Opens a web browser (Chrome, Edge, Firefox, Safari, or system default) across platforms. Optionally opens a specified URL.",
    platforms=["windows"],
    mode="GUI",
    action_sets=["gui_interaction"],
    parallelizable=False,
    input_schema={
        "url": {
                "type": "string",
                "example": "https://www.example.com",
                "description": "Optional URL to open in the browser."
        }
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' if a browser launched, 'error' otherwise."},
        "process_id": {"type": "integer", "example": 12345, "description": "Process ID of the launched browser instance when successful; -1 when opened via system default browser."},
        "browser": {"type": "string", "example": "chrome", "description": "Name of the browser that was launched."},
        "executable_path": {"type": "string", "example": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "description": "Absolute path to the browser executable used, if applicable."},
        "message": {"type": "string", "example": "Launched successfully.", "description": "Error or informational message."}
    },
)
def open_browser_windows(input_data: dict) -> dict:
    import os
    import subprocess
    import shutil
    import webbrowser
    import tempfile

    # Helper to get a temporary directory path for browser profiles.
    # Ensures every launch is a fresh instance and avoids profile locking issues.
    def _get_temp_profile_dir(prefix):
        try:
            return tempfile.mkdtemp(prefix=f"{prefix}_profile_")
        except Exception:
            return None

    url = str(input_data.get('url', '')).strip()

    candidates = [
        r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"),
        r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
        r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        r"C:\\Program Files\\Mozilla Firefox\\firefox.exe"
    ]

    try:
        browser_path = next((p for p in candidates if os.path.isfile(p)), None)
        if browser_path:
            cmd = [browser_path]
            
            # Force Temp Profile for Chromium browsers on Windows
            if "chrome" in browser_path.lower() or "edge" in browser_path.lower():
                 temp_dir = _get_temp_profile_dir("win_browser")
                 if temp_dir:
                     cmd.append(f'--user-data-dir={temp_dir}')

            if url:
                cmd.append(url)
            
            # CREATE_NEW_CONSOLE is excellent for Windows detachment.
            creation_flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
            
            proc = subprocess.Popen(
                cmd, 
                stdin=subprocess.DEVNULL,  # Isolate input
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL, 
                creationflags=creation_flags
            )
            
            msg = 'Launched specific browser successfully.'
            if "user-data-dir" in " ".join(cmd):
                 msg += " (Using temporary profile)."

            return {
                'status': 'success',
                'process_id': proc.pid,
                'browser': os.path.basename(browser_path).split('.')[0],
                'executable_path': browser_path,
                'message': msg
            }
        else:
            # Fallback
            if url:
                webbrowser.open(url)
            return {
                'status': 'success',
                'process_id': -1,
                'browser': 'default',
                'executable_path': '',
                'message': 'Opened URL using system default browser.'
            }
    except Exception as e:
        return {
            'status': 'error', 'process_id': -1, 'browser': '', 'executable_path': '', 'message': str(e)
        }

@action(
    name="open_browser",
    description="Opens a web browser (Chrome, Edge, Firefox, Safari, or system default) across platforms. Optionally opens a specified URL.",
    platforms=["darwin"],
    mode="GUI",
    action_sets=["gui_interaction"],
    input_schema={
        "url": {"type": "string", "example": "https://www.example.com", "description": "Optional URL to open in the browser."}
    },
    output_schema={
        "status": {"type": "string"}, "process_id": {"type": "integer"}, "browser": {"type": "string"}, "executable_path": {"type": "string"}, "message": {"type": "string"}
    },
)
def open_browser_darwin(input_data: dict) -> dict:
    import os
    import subprocess
    import shutil
    import webbrowser
    import tempfile

    # Helper (duplicated here for self-containment)
    def _get_temp_profile_dir(prefix):
        try:
            return tempfile.mkdtemp(prefix=f"{prefix}_profile_")
        except Exception:
            return None

    url = str(input_data.get('url', '')).strip()

    # Launching binaries directly inside .app bundles allows passing custom arguments reliable.
    candidates = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
        '/Applications/Firefox.app/Contents/MacOS/firefox',
    ]

    try:
        browser_path = next((p for p in candidates if os.path.isfile(p)), None)
        if browser_path:
            cmd = [browser_path]

            # Force Temp Profile on macOS to avoid locking issues
            if "Chrome" in browser_path or "Edge" in browser_path or "Brave" in browser_path:
                 temp_dir = _get_temp_profile_dir("mac_browser")
                 if temp_dir:
                     cmd.append(f'--user-data-dir={temp_dir}')

            if url:
                cmd.append(url)

            # Process Detachment for macOS using start_new_session
            proc = subprocess.Popen(
                cmd, 
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            msg = 'Launched specific browser successfully.'
            if "user-data-dir" in " ".join(cmd):
                 msg += " (Using temporary profile)."

            return {
                'status': 'success',
                'process_id': proc.pid,
                'browser': os.path.basename(browser_path).split('.')[0],
                'executable_path': browser_path,
                'message': msg
            }
        else:
            # Fallback
            if url:
                webbrowser.open(url)
            return {
                'status': 'success',
                'process_id': -1,
                'browser': 'default',
                'executable_path': '',
                'message': 'Opened URL using system default browser (Safari likely).'
            }
    except Exception as e:
        return {
            'status': 'error', 'process_id': -1, 'browser': '', 'executable_path': '', 'message': str(e)
        }

@action(
    name="open_browser",
    description="Opens a web browser (Chrome, Edge, Firefox, Safari, or system default) across platforms. Optionally opens a specified URL.",
    platforms=["linux"],
    mode="GUI",
    action_sets=["gui_interaction"],
    input_schema={ "url": {"type": "string"} },
    output_schema={ "status": {"type": "string"}, "process_id": {"type": "integer"}, "browser": {"type": "string"}, "executable_path": {"type": "string"}, "message": {"type": "string"} },
)
def open_browser_linux(input_data: dict) -> dict:
    import os
    import subprocess
    import shutil
    import webbrowser

    url = str(input_data.get('url', '')).strip()

    candidates = [
        shutil.which('google-chrome'),
        shutil.which('google-chrome-stable'),
        shutil.which('chromium'),
        shutil.which('chromium-browser'),
        shutil.which('brave-browser'),
        shutil.which('firefox'),
        shutil.which('microsoft-edge')
    ]

    try:
        browser_path = next((p for p in candidates if p and os.path.isfile(p)), None)
        if browser_path:
            cmd = [browser_path, '--no-sandbox', '--temp-profile']
            if url:
                cmd.append(url)

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
                close_fds=True
            )

            return {
                'status': 'success',
                'process_id': proc.pid,
                'browser': os.path.basename(browser_path),
                'executable_path': browser_path,
                'message': f'Launched {os.path.basename(browser_path)} with temp profile.'
            }
        else:
            if url:
                webbrowser.open(url)
            return {
                'status': 'success',
                'process_id': -1,
                'browser': 'default system',
                'executable_path': '',
                'message': 'Attempted to open URL using system default mechanism.'
            }

    except Exception as e:
        return {
            'status': 'error', 'process_id': -1, 'browser': '', 'executable_path': '', 'message': str(e)
        }