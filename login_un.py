import os
import sys

# 1. Automatic virtual environment reloader at the absolute top
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")
    if os.path.exists(venv_python) and sys.executable != venv_python:
        print("[System] Reloader: Relaunching via virtual environment...")
        os.execv(venv_python, [venv_python] + sys.argv)
    else:
        print("[Error] Playwright is not installed.")
        sys.exit(1)

import time

def main():
    print("====================================================")
    print("UN CAREERS (INSPIRA) SESSION REFRESHER")
    print("====================================================")
    print("This script will open a browser window to let you log in to Inspira.")
    print("Please enter your UN Careers username and password and log in.")
    print("Once you are logged in and see your dashboard page, press ENTER here in this terminal to save.")
    print("----------------------------------------------------\n")
    
    state_file = "storage_state.json"
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()
            page.goto("https://inspira.un.org", wait_until="domcontentloaded", timeout=60000)
            
            input("\n[PROMPT] Log in manually in the browser. Once you are logged in, press ENTER here in the terminal to save your session...")
            
            print("\nSaving session state...")
            context.storage_state(path=state_file)
            print(f"[SUCCESS] Session saved successfully to '{state_file}'!")
            
            browser.close()
        except Exception as e:
            print(f"\n[ERROR] Playwright session solver failed: {e}")

if __name__ == "__main__":
    main()
