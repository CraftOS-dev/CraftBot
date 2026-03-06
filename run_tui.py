#!/usr/bin/env python3
"""
CraftBot TUI Launcher - Direct Interface
Starts the TUI without Docker dependencies
"""
import os
import sys
import asyncio

# Load .env first
def load_env():
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if line.strip() and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

load_env()

print("Initializing CraftBot TUI...")
print(f"LLM Provider: {os.getenv('LLM_PROVIDER', 'anthropic')}")

try:
    # Try to import and run the TUI
    print("Loading core modules...")
    from core.tui.interface import CraftBotTUI
    import asyncio
    
    # Run the TUI
    async def main():
        tui = CraftBotTUI()
        await tui.run()
    
    asyncio.run(main())
    
except ImportError as e:
    print(f"⚠️  Cannot load TUI: {e}")
    print("\nFalling back to CLI interface...\n")
    
    # Fallback to CLI
    import subprocess
    result = subprocess.run([sys.executable, "craftbot_cli.py"])
    sys.exit(result.returncode)

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
