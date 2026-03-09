#!/usr/bin/env python3
"""Demo of the new progress bar"""
import time
import sys

def show_progress_bar():
    message = "Installing dependencies..."
    bar_length = 30
    
    for percent in range(0, 101, 5):
        filled = int(bar_length * percent / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        sys.stdout.write(f"\r{message} [{bar}] {percent}%")
        sys.stdout.flush()
        time.sleep(0.2)
    
    # Complete
    filled = bar_length
    bar = "█" * filled
    sys.stdout.write(f"\r{message} [{bar}] 100%\n")
    sys.stdout.flush()

print("CraftBot Installation\n")
show_progress_bar()
print("✓ Dependencies installed\n")

show_progress_bar()
print("✓ Installation Complete!\n")
print("="*50)
print("✓ Installation Complete!")
print("="*50)
print("\nLaunching CraftBot...\n")
