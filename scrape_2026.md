# Deep Dive into the Gesamtkunstwerk Scraper

This document provides a meticulous explanation of the `scraper.py` file, the core data collection engine of the application.

### 1. High-Level Strategy & Orchestration

The primary goal of `scraper.py` is to automate the tedious process of finding relevant job opportunities. It achieves this through a multi-stage pipeline:

1.  **Configuration:** It starts by loading the user's preferences (keywords, locations, target platforms) from `settings.json`.
2.  **Execution:** It runs individual scraper functions for different job boards **concurrently** using Python's `threading` module. This parallelism is crucial for efficiency, as it allows the script to fetch data from multiple sites at once instead of waiting for each one to finish in sequence.
3.  **Scraping & Filtering:** Each scraper fetches raw job listings and performs an initial, lightweight filtering using the `matches_profile` function to see if a job is worth investigating further.
4.  **Enrichment (AI):** For jobs that pass the initial filter, the scraper fetches the full job description and sends it to the Google Gemini API via the `get_ai_evaluation` function. The AI provides a relevance score, a justification, and key requirements.
5.  **Persistence:** Finally, any job that is deemed a match is saved to the SQLite database via functions in `db.py`.

The main function, `run_pipeline()`, orchestrates this entire process, launching each scraper in a separate thread and waiting for them to complete.

---

### 2. Core Components & Concepts

Before looking at individual scrapers, it's important to understand the shared components they all rely on.

#### **Configuration (`load_settings`)**
This function reads the `settings.json` file and loads your keywords, locations, chosen platforms, and AI credentials into global variables. This is how your preferences in the UI control the scraper's behavior. It also has a command-line override (`--override-keywords`) for running scans with temporary keywords.

#### **Filtering (`matches_profile`)**
This is the first gatekeeper for quality. After a scraper gets a job title and description, it calls this function.
*   It converts all text to lowercase for case-insensitive matching.
*   It checks if the text contains the required keywords. It respects the `AND`/`OR` logic set in the settings:
    *   **OR Mode:** The job is a match if *any* of your keywords are found.
    *   **AND Mode:** The job is only a match if *all* of your keywords are found.
*   It also checks if the job's location matches any of your target locations. If you haven't specified any locations, this check is skipped.

#### **AI Enrichment & Caching (`get_ai_evaluation`)**
This is where the "magic" happens. For a promising job, this function:
1.  **Constructs a Prompt:** It builds a detailed prompt for the Gemini API, telling it to act as a career assistant. The prompt includes your professional profile summary (from settings) and the full text of the job description.
2.  **Queries the AI:** It asks the AI to return a JSON object containing three specific fields:
    *   `match_score`: A percentage (0-100) of how well the job fits your profile.
    *   `match_reason`: A short, human-readable sentence explaining the score.
    *   `key_requirements`: A bulleted list of the most important skills the job requires.
3.  **Caches the Result:** To save time and money on API calls, it maintains a local cache in `evaluation_cache.json`. Before querying the AI, it checks if it has evaluated this exact job URL before. If so, it retrieves the previous result from the cache instead of calling the API again.

---

### 3. Individual Scraper Strategies

The script uses different strategies for different websites, as each has its own structure and anti-scraping defenses.

#### **`scrape_daleel_madani` (Hybrid Strategy)**
*   **Challenge:** This site is protected by Cloudflare, which blocks simple automated requests.
*   **Solution:** This scraper uses a clever hybrid approach.
    1.  **Cookie-based Access:** It first tries to use valid session cookies from a file (`daleel_cookies.json`). It uses the `curl_cffi` library, which can impersonate a real browser's TLS fingerprint, making its requests look less like a bot.
    2.  **Automated Solver:** If the cookies are missing or expired (i.e., Cloudflare presents a challenge), the `auto_solve_daleel_cookies` function is triggered. It uses the **Playwright** library to launch a **visible browser window**. It then waits for you, the user, to solve the Cloudflare CAPTCHA (e.g., click the "I am human" checkbox). Once you solve it, the scraper saves the new, valid session cookies for future runs.

#### **`scrape_un_careers` (Full Browser Automation)**
*   **Challenge:** The UN Inspira portal is a notoriously difficult-to-scrape Oracle PeopleSoft application. It's built entirely with JavaScript, has a complex state, and requires a login.
*   **Solution:** This scraper uses **Playwright** to fully automate a browser.
    1.  **Login & Session Persistence:** It launches a browser, navigates to the login page, and enters the username/password from your settings. After a successful login, it saves the entire browser session state (cookies, local storage) to `storage_state.json`. On subsequent runs, it loads this file to bypass the login step, which is much faster.
    2.  **Navigating the UI:** It programmatically clicks buttons to navigate to the job search page, enter search terms, and click through paginated results.
    3.  **Deep Linking:** As an optimization, it tries to extract the `JobOpeningId` from a listing and construct a direct URL to the detail page. This is faster than simulating a click and waiting for the page to navigate.
    4.  **Error Handling:** It contains logic to handle session expiry, pop-up modals, and other dynamic UI elements that can interrupt the scraping flow.

#### **`scrape_linkedin`, `scrape_reliefweb`, `scrape_bayt` (Standard HTTP Scraping)**
*   **Challenge:** These sites are more traditional. The main challenge is parsing the HTML correctly and avoiding basic rate-limiting.
*   **Solution:** These scrapers are simpler.
    1.  **HTTP Requests:** They use `curl_cffi` or `requests` to make standard GET requests to the sites' search URLs, passing keywords and locations as query parameters.
    2.  **HTML Parsing:** They use the **BeautifulSoup** library to parse the returned HTML content.
    3.  **CSS Selectors:** They use specific CSS selectors (e.g., `.base-search-card__title`, `.rw-river-article`) to find the HTML elements that contain the job title, company, location, and link for each listing.
    4.  **Politeness:** They include small `time.sleep()` delays between requests to avoid overwhelming the servers.
