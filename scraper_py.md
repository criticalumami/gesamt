# An Excruciatingly Detailed Guide to scraper.py

This document dissects the `scraper.py` file, the heart of the application's data-gathering capabilities.

### 1. Preamble: Setup and Configuration

The script begins not with imports, but with a unique self-reloading mechanism.

```python
# Automatic virtual environment reloader
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    venv_python = os.path.join(...)
    if os.path.exists(venv_python) and sys.executable != venv_python:
        print("[System] Reloader: Relaunching via virtual environment...")
        os.execv(venv_python, [venv_python] + sys.argv)
```
*   **What it does:** This code attempts to import `playwright`. If it fails (meaning the script is likely running outside its dedicated virtual environment), it checks for the existence of `venv/bin/python`. If found, it uses `os.execv` to **restart itself** using that correct Python interpreter.
*   **Why it's there:** This is a clever, albeit non-standard, way to ensure the script always runs with the correct dependencies specified in `requirements.txt`, even if the user accidentally runs it with their system's global Python.

Following this are the standard imports (`requests`, `BeautifulSoup`, etc.) and the configuration loading.

```python
def load_settings():
    if os.path.exists("settings.json"):
        # ... loads from file
    return DEFAULT_KEYWORDS, DEFAULT_LOCATIONS, ...

KEYWORDS, LOCATIONS, ... = load_settings()

parser = argparse.ArgumentParser(...)
parser.add_argument("--override-keywords", ...)
args, unknown = parser.parse_known_args()
if args.override_keywords:
    KEYWORDS = ...
```
*   **What it does:** The `load_settings` function safely loads configuration from `settings.json`. If the file doesn't exist, or if a specific key is missing, it falls back to a hardcoded `DEFAULT_` value. This makes the script resilient and runnable out-of-the-box.
*   **The `argparse` section** allows for overriding the keywords directly from the command line when the script is launched (which is exactly what `server.py` does when you search in the UI and click "Scan Job Boards").

---

### 2. The Core Toolkit: Reusable Helper Functions

These are the foundational utilities that all the individual scrapers use.

#### **`http_get_with_retry(...)`**
This is a mission-critical utility for any serious scraper.
*   **What it does:** It wraps a standard HTTP GET request in a `for` loop to automatically retry it up to 3 times if it fails.
*   **Why it's so detailed:**
    *   **Exponential Backoff:** It doesn't just retry immediately. It waits for `backoff * (2 ** attempt)` seconds between tries (e.g., 1s, then 2s, then 4s). This is a best practice that gives a struggling server time to recover and avoids getting your IP address banned for being too aggressive.
    *   **Specific Error Handling:** It's programmed to retry not just on network errors, but also on specific HTTP status codes that indicate temporary server issues (`500`, `502`, `503`, `504`) or rate-limiting (`429`).

#### **`get_ai_evaluation(...)`**
This is the core AI function. Its implementation reveals a lot about how to get reliable results from an LLM.
*   **Local Caching:** Before doing anything, it checks a local file `evaluation_cache.json`. If the job's URL is already in this cache, it immediately returns the previously saved result.
    *   > **Why?** This is a crucial optimization. It prevents the script from making expensive and slow API calls to Gemini for the same job it might have seen in a previous scan.
*   **Prompt Engineering:** The prompt is not just a simple question. It's carefully engineered:
    1.  **Persona:** `You are an expert career assistant.` This puts the AI in the correct "mindset."
    2.  **Context:** It provides your `PROFILE_SUMMARY` and `LOCATIONS` so the AI knows what you're looking for.
    3.  **The Data:** It injects the full job title, location, and description.
    4.  **Strict Output Formatting:** It ends with `Respond ONLY with a JSON object in this format...`. This is the most important part. It forces the AI to return clean, structured data that the Python code can parse with `json.loads()`, rather than a conversational, unpredictable text response.
*   **Thread Safety:** It uses a `threading.Lock` (`cache_lock`) when reading from or writing to the cache file.
    *   > **Why?** The main pipeline runs scrapers in parallel threads. Without a lock, two threads could try to write to the cache file at the same time, corrupting it. The lock ensures that only one thread can access the file at any given moment.

---

### 3. The Scrapers: A Tale of Different Strategies

Each `scrape_...` function is tailored to its target website.

#### **`scrape_daleel_madani(...)`**
*   **Strategy:** A hybrid approach to defeat Cloudflare's anti-bot protection.
*   **Step-by-Step:**
    1.  It first calls `get_daleel_madani_cookies()`, which tries to load valid session cookies from `daleel_cookies.json`.
    2.  It validates these cookies by making a test request with `curl_cffi`, a library that impersonates a real browser's network fingerprint to appear more "human."
    3.  **If validation fails,** it triggers `auto_solve_daleel_cookies()`. This function uses **Playwright** to launch a **visible browser window** and navigate to the site. It then pauses and waits for you, the human, to solve the Cloudflare CAPTCHA. Once you do, it saves the resulting valid cookies for the next run.
    4.  With valid cookies, it iterates through your keywords, fetching search result pages.
    5.  It uses a `ThreadPoolExecutor` to fetch the detail pages for multiple jobs **concurrently**, a major performance boost.
    6.  For each job, it filters, evaluates with AI, and saves, just like the others.

#### **`scrape_un_careers(...)`**
*   **Strategy:** Full browser automation with Playwright to navigate a complex, JavaScript-heavy portal.
*   **Step-by-Step:**
    1.  It launches a Chromium browser managed by Playwright.
    2.  It first tries to load a saved session from `storage_state.json`. This file contains cookies and local storage data that can keep you logged in across multiple runs.
    3.  If it's not logged in, it calls `perform_un_login()`, which programmatically types your username and password into the form fields.
    4.  It navigates directly to the job search page URL, a faster alternative to clicking through the UI.
    5.  **It handles the `ptifrmtgtframe` iframe.** This is a critical detail. Many enterprise web apps place their main content inside an `<iframe>`. The code must explicitly target this frame (`target = page.frame_locator(...)`) to be able to find any elements within it.
    6.  It iterates through the rows of the job table. For each row, it attempts an **optimization**: it tries to parse the Job ID from the title and construct a direct "deep link" to the details page.
    7.  If the deep link works, it opens it in a new tab for speed. If it fails, it falls back to the slower method of simulating a click on the job title link, waiting for the page to load, scraping the content, and then simulating a click on the "Back" button.
    8.  The rest of the process (AI evaluation, saving) follows.

#### **`scrape_oea(...)` and other HTTP scrapers**
*   **Strategy:** Simpler HTTP requests combined with HTML parsing.
*   **Step-by-Step:**
    1.  These scrapers use `curl_cffi` or `requests` to fetch the HTML of search result pages.
    2.  They use **BeautifulSoup** to parse the HTML.
    3.  They find job listings using specific CSS selectors (e.g., `soup.find_all(class_="type-career")`).
    4.  A unique feature of the `scrape_oea` function is the `decode_cf_email` helper. OEA's website obfuscates email addresses to protect them from simple scrapers. This function reverses their specific character-encoding scheme to reveal the real email address.
    5.  They loop through the results, fetch details, filter, evaluate with AI, and save. They include a `time.sleep(1)` delay between requests to be polite and avoid rate-limiting.
