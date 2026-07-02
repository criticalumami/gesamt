import time
import json
import os
import sys
import threading
# Automatic virtual environment reloader
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")
    if os.path.exists(venv_python) and sys.executable != venv_python:
        print("[System] Reloader: Relaunching via virtual environment...")
        os.execv(venv_python, [venv_python] + sys.argv)
    else:
        print("[Error] Required packages are not installed.")
        sys.exit(1)

def main():
    print("====================================================")
    print("DALEEL MADANI CLOUDFLARE COOKIE SOLVER")
    print("====================================================")
    print("This script opens a browser to bypass Cloudflare Turnstile.")
    print("Please click the 'Verify you are human' checkbox in the browser window.")
    print("----------------------------------------------------\n")
    
    cookie_file = "daleel_cookies.json"
    
    import tempfile
    import shutil
    user_data_dir = tempfile.mkdtemp()
    
    with sync_playwright() as p:
        try:
            # Try launching with Webkit (Safari engine)
            try:
                context = p.webkit.launch_persistent_context(
                    user_data_dir,
                    headless=False,
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                    viewport={"width": 1280, "height": 800}
                )
            except Exception as we:
                print(f"Webkit launch failed ({we}), falling back to Chrome...")
                # Fallback to Chrome
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir,
                        headless=False,
                        channel="chrome",
                        ignore_default_args=["--enable-automation", "--no-sandbox"],
                        args=["--disable-blink-features=AutomationControlled"],
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 800}
                    )
                except Exception:
                    # Fallback to stock Chromium
                    context = p.chromium.launch_persistent_context(
                        user_data_dir,
                        headless=False,
                        ignore_default_args=["--enable-automation", "--no-sandbox"],
                        args=["--disable-blink-features=AutomationControlled"],
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 800}
                    )
                
            page = context.pages[0] if context.pages else context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto("https://daleel-madani.org/jobs", wait_until="domcontentloaded", timeout=60000)
            
            print("👉 **Check the opened browser window and solve the Cloudflare checkbox if prompted.**")
            
            # Set up manual terminal enter fallback thread
            user_pressed_enter = False
            def wait_for_user():
                nonlocal user_pressed_enter
                try:
                    input("\n[PROMPT] Or, if the listings load and the script doesn't close, press ENTER here to force capture...")
                except Exception:
                    pass
                user_pressed_enter = True
                
            t = threading.Thread(target=wait_for_user)
            t.daemon = True
            t.start()
            
            solved = False
            for s in range(60):  # Wait up to 60 seconds
                if user_pressed_enter or page.locator(".views-row").count() > 0 or page.locator(".view-content").count() > 0:
                    print("\n[SUCCESS] Cloudflare Turnstile bypassed!")
                    cookies = context.cookies()
                    user_agent = page.evaluate("navigator.userAgent")
                    
                    with open(cookie_file, "w") as f:
                        json.dump({"cookies": cookies, "user_agent": user_agent}, f, indent=2)
                    print(f"Saved valid session cookies to '{cookie_file}'.")
                    solved = True
                    break
                time.sleep(1)
                
            context.close()
            if not solved:
                print("\n[TIMEOUT] Solver timed out. Please try again.")
        except Exception as e:
            print(f"\n[ERROR] Playwright headed solver failed: {e}")
        finally:
            try:
                shutil.rmtree(user_data_dir, ignore_errors=True)
            except Exception:
                pass

if __name__ == "__main__":
    main()
