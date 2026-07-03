import os
import sys

# Automatic virtual environment reloader
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")
    if os.path.exists(venv_python) and sys.executable != venv_python:
        print("[System] Reloader: Relaunching via virtual environment...")
        os.execv(venv_python, [venv_python] + sys.argv)
    else:
        print("[Error] Required packages are not installed in the environment.")
        sys.exit(1)

import time
import json
import pandas as pd
import requests
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import db
db.init_db()


# --- Configuration ---
DEFAULT_KEYWORDS = ["urban planning", "heritage conservation", "architecture", "urban research", "qgis"]
DEFAULT_LOCATIONS = ["beirut", "paris", "berlin", "hamburg"]
DEFAULT_PLATFORMS = ["Daleel Madani", "UN Careers", "ReliefWeb", "LinkedIn", "Bayt.com"]

def load_settings():
    if os.path.exists("settings.json"):
        try:
            with open("settings.json", "r") as f:
                data = json.load(f)
                return (
                    data.get("keywords", DEFAULT_KEYWORDS),
                    data.get("locations", DEFAULT_LOCATIONS),
                    data.get("platforms", DEFAULT_PLATFORMS),
                    data.get("un_username", ""),
                    data.get("un_password", ""),
                    data.get("gemini_api_key", ""),
                    data.get("profile_summary", ""),
                    data.get("ai_enabled", True),
                    data.get("keyword_mode", "OR"),
                    data.get("gemini_model", "gemini-flash-latest")
                )
        except Exception:
            pass
    return DEFAULT_KEYWORDS, DEFAULT_LOCATIONS, DEFAULT_PLATFORMS, "", "", "", "", True, "OR", "gemini-flash-latest"

KEYWORDS, LOCATIONS, PLATFORMS, UN_USERNAME, UN_PASSWORD, GEMINI_API_KEY, PROFILE_SUMMARY, AI_ENABLED, KEYWORD_MODE, GEMINI_MODEL = load_settings()

# Check for command line keyword overrides
import argparse
parser = argparse.ArgumentParser(description="Gesamtkunstwerk Scraper")
parser.add_argument("--override-keywords", type=str, default="", help="Comma-separated keywords to override settings")
args, unknown = parser.parse_known_args()

if args.override_keywords:
    override_list = [k.strip() for k in args.override_keywords.split(",") if k.strip()]
    if override_list:
        KEYWORDS = override_list
        print(f"[Pipeline] Active Keywords Overridden by Command Line: {KEYWORDS}")

# Convert HEADLESS env var to boolean, default to True
HEADLESS_ENV = os.getenv("HEADLESS", "True")
HEADLESS = HEADLESS_ENV.lower() in ("true", "1", "yes")

# Delays to prevent rate-limiting (in seconds)
REQUEST_DELAY = 3  # delay between detail page requests
PAGE_DELAY = 5     # delay between main pages

import threading

def load_existing_urls():
    """Return a set of URLs already saved in the SQLite database (Applied and Archived)."""
    try:
        df = db.get_all_jobs_df()
        tracked = df[df["Status"].isin(["Applied", "Archived"])]
        return set(tracked["URL"].dropna().tolist())
    except Exception as e:
        print(f"[Database] Error loading existing URLs: {e}")
        return set()


def clean_description(desc_text):
    if not desc_text:
        return "No description available."
    cleaned = " ".join(desc_text.split())
    if len(cleaned) > 200:
        return cleaned[:200] + "..."
    return cleaned

# --- HTTP Retry Helper ---
def http_get_with_retry(url, *, session=None, retries=3, backoff=1, **kwargs):
    """
    GET request with exponential-backoff retry.
    Pass session= for a curl_cffi or requests Session; otherwise uses requests.get.
    Retries on network errors and 5xx / 429 status codes.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            if session is not None:
                r = session.get(url, **kwargs)
            else:
                r = requests.get(url, **kwargs)
            if r.status_code == 429 and attempt < retries - 1:
                import random
                wait = 15 * (2 ** attempt) + random.uniform(2.0, 5.0)
                print(f"    [Rate Limit] HTTP 429. Backing off for {wait:.1f}s before retry...")
                time.sleep(wait)
                continue
            if r.status_code in (500, 502, 503, 504) and attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                print(f"    [Retry] HTTP {r.status_code} on attempt {attempt+1}. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            return r
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                print(f"    [Retry] Error on attempt {attempt+1} ({e}). Retrying in {wait}s...")
                time.sleep(wait)
    if last_exc:
        raise last_exc



# --- Helper Functions ---
def matches_profile(title, description, location=""):
    """
    Returns True if the job matches the profile logic:
    If keywords are set, it must match at least one keyword.
    If locations are set, it must match at least one location.
    """
    text = f"{title} {description} {location}".lower()

    # Check keywords — OR mode: any keyword matches; AND mode: all must match
    if not KEYWORDS:
        has_keyword = True
    elif KEYWORD_MODE == "AND":
        has_keyword = all(kw.lower() in text for kw in KEYWORDS)
    else:  # OR (default)
        has_keyword = any(kw.lower() in text for kw in KEYWORDS)

    # Check locations (if none specified, treat as match)
    has_location = not LOCATIONS or any(loc.lower() in text for loc in LOCATIONS)

    return has_keyword and has_location

# --- Gemini AI Evaluation Helper with Local Cache ---
import threading
CACHE_FILE = "evaluation_cache.json"
cache_lock = threading.Lock()

def load_evaluation_cache():
    with cache_lock:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

def save_evaluation_cache(cache):
    with cache_lock:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Cache] Warning: Could not write cache file: {e}")

def get_ai_evaluation(title, description, location="", job_url=""):
    cache_key = job_url if job_url else title
    if cache_key:
        cache = load_evaluation_cache()
        if cache_key in cache:
            entry = cache[cache_key]
            print(f"[Cache] Retrieved evaluation for '{title}' from local cache.")
            return entry.get("score", 0), entry.get("reason", ""), entry.get("requirements", [])

    if not AI_ENABLED:
        return 0, "AI evaluation disabled in settings.", []

    if not GEMINI_API_KEY:
        return 0, "AI evaluation skipped (no API key configured).", []
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    profile_context = f"- Candidate Profile: {PROFILE_SUMMARY}" if PROFILE_SUMMARY else f"- Target Keywords: {', '.join(KEYWORDS)}"
    
    prompt = f"""You are an expert career assistant. Analyze this job listing for a candidate with the following profile:
{profile_context}
- Target Locations: {', '.join(LOCATIONS)}

Job Title: {title}
Job Location: {location}
Job Description: {description}

Determine:
1. Match Score (0 to 100%): How well does this job match the target profile?
2. Match Reason (Maximum 2 sentences): A concise explanation of why it is a good or poor match.
3. Key Requirements (3-5 bullet points): Core technical skills or software required (e.g. QGIS, Revit, AutoCAD, planning policies).

Respond ONLY with a JSON object in this format (no markdown code blocks, no backticks, just raw JSON):
{{
  "match_score": 85,
  "match_reason": "Description...",
  "key_requirements": ["Requirement 1", "Requirement 2"]
}}"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            error_message = f"API returned status {r.status_code}: {r.text}"
            print(f"[Gemini API] Warning: {error_message}")
            return 0, error_message, []

        res_json = r.json()
        text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
        import re
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)
        
        parsed = json.loads(text)
        score = int(parsed.get("match_score", 0))
        reason = parsed.get("match_reason", "No reason provided.")
        reqs = parsed.get("key_requirements", [])
        
        # Write to cache
        if cache_key:
            cache = load_evaluation_cache()
            cache[cache_key] = {
                "title": title,
                "score": score,
                "reason": reason,
                "requirements": reqs
            }
            save_evaluation_cache(cache)
            
        return score, reason, reqs
    except requests.exceptions.RequestException as ex:
        error_message = f"Network error during AI evaluation: {ex}"
        print(f"[Gemini API] Warning: {error_message}")
        return 0, error_message, []
    except (KeyError, IndexError, json.JSONDecodeError) as ex:
        error_message = f"Error parsing AI API response: {ex}"
        print(f"[Gemini API] Warning: {error_message}")
        return 0, error_message, []
    except Exception as ex:
        error_message = f"An unexpected error occurred during AI evaluation: {ex}"
        print(f"[Gemini API] Warning: {error_message}")
        return 0, error_message, []


# --- AI Keyword Expansion ---
def expand_keywords_with_ai(profile_summary, current_keywords, api_key):
    if not api_key:
        return False, "No Gemini API Key configured."
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    prompt = f"""Given this candidate profile summary:
"{profile_summary}"

And their current target keywords:
{json.dumps(current_keywords)}

Generate an expanded list of 8 to 12 highly relevant job search keywords (in English) that this candidate should search for on job boards (such as LinkedIn, EURAXESS, Daleel Madani, etc.).
You MUST output single-word root terms or short, distinct words (e.g., architect, planner, planning, designer, GIS, research, conservation, development, landscape, spatial, academic) rather than long compound multi-word phrases. This ensures maximum match coverage in the exact-matching pipeline.
Respond ONLY with a JSON array of strings (no backticks, no markdown formatting), for example:
["keyword1", "keyword2", "keyword3"]"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code == 200:
            res_json = r.json()
            text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            import re
            json_match = re.search(r"\[.*\]", text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            
            expanded = json.loads(text)
            if isinstance(expanded, list):
                return True, [str(x).strip() for x in expanded]
            return False, "Failed to parse JSON response list."
        else:
            try:
                err_msg = r.json().get("error", {}).get("message", f"HTTP Status {r.status_code}")
            except Exception:
                err_msg = f"HTTP Status {r.status_code}"
            return False, err_msg
    except Exception as e:
        return False, str(e)


# --- Daleel Madani Scraper ---
def auto_solve_daleel_cookies():
    print("\n[Daleel Madani] Cloudflare cookies missing or expired. Launching headed browser solver...")
    print("👉 **Please check the opened browser window and solve the Cloudflare checkbox if prompted.**")
    
    cookie_file = "daleel_cookies.json"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[Daleel Madani] Error: playwright is not installed. Skipping auto-solver.")
        return None, None
        
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
                print(f"[Daleel Madani] Webkit launch failed ({we}), falling back to Chrome...")
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
            
            # Wait up to 60 seconds for page content to load
            solved = False
            for _ in range(60):
                if page.locator(".views-row").count() > 0 or page.locator(".view-content").count() > 0:
                    print("[Daleel Madani] Success: Cloudflare Turnstile bypassed!")
                    cookies = context.cookies()
                    user_agent = page.evaluate("navigator.userAgent")
                    
                    with open(cookie_file, "w") as f:
                        json.dump({"cookies": cookies, "user_agent": user_agent}, f, indent=2)
                    print(f"[Daleel Madani] Saved valid session cookies to '{cookie_file}'.")
                    solved = True
                    break
                time.sleep(1)
                
            context.close()
            if solved:
                return cookies, user_agent
        except Exception as e:
            print(f"[Daleel Madani] Headed solver failed: {e}")
        finally:
            try:
                shutil.rmtree(user_data_dir, ignore_errors=True)
            except Exception:
                pass
    return None, None

def get_daleel_madani_cookies():
    """
    Retrieves cookies using a cached JSON file imported from the user's browser.
    """
    cookie_file = "daleel_cookies.json"
    
    # 1. Try loading cached cookies
    if os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r") as f:
                data = json.load(f)
                cookies = data.get("cookies", [])
                user_agent = data.get("user_agent", "")
                
            if cookies and user_agent:
                # Validate cached cookies with a fast request
                session = curl_requests.Session(impersonate="chrome")
                session.headers.update({"User-Agent": user_agent})
                for cookie in cookies:
                    session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                
                print("[Daleel Madani] Validating cached cookies...")
                r = http_get_with_retry("https://daleel-madani.org/jobs", session=session, timeout=10)
                if r.status_code == 200:
                    soup_check = BeautifulSoup(r.text, "html.parser")
                    has_jobs = bool(soup_check.select(".views-row") or soup_check.select(".view-content"))
                    is_challenge = "Just a moment" in r.text or "Cloudflare" in r.text or soup_check.select("noscript")
                    if has_jobs and not is_challenge:
                        print("[Daleel Madani] Success: Cached cookies are valid!")
                        return cookies, user_agent
                    else:
                        print("[Daleel Madani] Cached cookies are invalid or expired (challenge page or no job rows found).")
                else:
                    print(f"[Daleel Madani] Cached cookies rejected — HTTP {r.status_code}.")
        except Exception as ce:
            print(f"[Daleel Madani] Error loading cached cookies: {ce}")
            
    # 2. Trigger headed solver auto-recovery
    cookies, user_agent = auto_solve_daleel_cookies()
    if cookies and user_agent:
        return cookies, user_agent
        
    print("\n--- [Daleel Madani] Cloudflare cookies are missing or expired ---")
    print("  👉 Manual backup: run python solve_cookies.py in terminal.")
    return None, None

def scrape_daleel_madani(existing_urls=None):
    """
    Scrapes job listings from Daleel Madani and filters them
    """
    cookies, user_agent = get_daleel_madani_cookies()
    if not cookies:
        print("[Daleel Madani] Failed to retrieve session cookies. Skipping Daleel Madani.")
        return []
        
    print(f"[Daleel Madani] Setting up requests.Session() with {len(cookies)} cookies.")
    session = curl_requests.Session(impersonate="chrome")
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    })
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
        
    matched_jobs = []
    if existing_urls is None:
        existing_urls = set()

    def fetch_job_detail(job, cookies_dict):
        try:
            r = curl_requests.get(
                job["url"],
                impersonate="chrome",
                cookies=cookies_dict,
                headers={"User-Agent": user_agent},
                timeout=15
            )
            if r.status_code == 200:
                detail_soup = BeautifulSoup(r.text, "html.parser")
                desc_elem = (
                    detail_soup.select_one(".field-name-body") or
                    detail_soup.select_one(".field--name-body") or 
                    detail_soup.select_one(".node__content") or 
                    detail_soup.select_one("article")
                )
                description = desc_elem.text.strip() if desc_elem else ""
                
                deadline_elem = (
                    detail_soup.select_one(".field--name-field-job-deadline .field__item") or
                    detail_soup.select_one(".field--name-field-application-deadline .field__item") or
                    detail_soup.select_one("[class*='deadline'] .field__item")
                )
                deadline = deadline_elem.text.strip() if deadline_elem else "N/A"
                
                return {
                    "success": True,
                    "title": job["title"],
                    "location": job["location"],
                    "url": job["url"],
                    "description": description,
                    "deadline": deadline
                }
            else:
                return {"success": False, "title": job["title"], "status": r.status_code}
        except Exception as e:
            return {"success": False, "title": job["title"], "error": str(e)}

    # Scrape by keywords using fulltext search API
    from concurrent.futures import ThreadPoolExecutor
    seen_urls = set()
    
    for kw in KEYWORDS:
        print(f"\n[Daleel Madani] Searching keyword: '{kw}'...")
        for page_num in range(2):
            url = f"https://daleel-madani.org/jobs?search_api_views_fulltext={kw}&page={page_num}"
            print(f"  Fetching page {page_num + 1}: {url}")
            
            try:
                response = session.get(url, timeout=20)
                if response.status_code != 200:
                    print(f"    Failed to fetch search page {page_num + 1}. Status: {response.status_code}")
                    if response.status_code == 403:
                        print("    Cookies rejected by Cloudflare (403).")
                    break
                    
                soup = BeautifulSoup(response.text, "html.parser")
                rows = soup.select(".views-row")
                print(f"    Found {len(rows)} job listings on page {page_num + 1}.")
                
                if not rows:
                    break
                    
                jobs_to_check = []
                for row in rows:
                    title_elem = row.select_one(".field-name-title-field h4 a, h4 a, .views-field-title-1 a")
                    if not title_elem:
                        continue
                        
                    title = title_elem.text.strip()
                    href = title_elem.get("href", "")
                    detail_url = f"https://daleel-madani.org{href}" if href.startswith("/") else href
                    
                    if detail_url in seen_urls:
                        continue
                    seen_urls.add(detail_url)
                    
                    if detail_url in existing_urls:
                        continue
                        
                    cached_job = db.get_cached_job(detail_url)
                    if cached_job:
                        print(f"    [Cache] Restored cached match details for: '{title}'")
                        cached_job["Status"] = "New"
                        db.save_job(cached_job)
                        matched_jobs.append(cached_job)
                        continue
                    
                    location_elem = row.select_one(".field-name-field-locations, .field-name-field-location, .shs-hierarchy")
                    if location_elem:
                        li_items = location_elem.select("li")
                        if li_items:
                            listing_location = " > ".join([li.text.strip() for li in li_items])
                        else:
                            listing_location = location_elem.text.strip()
                    else:
                        listing_location = "Lebanon"
                    
                    jobs_to_check.append({
                        "title": title,
                        "url": detail_url,
                        "location": listing_location
                    })
                    
                if jobs_to_check:
                    print(f"    [Daleel Madani] Checking {len(jobs_to_check)} details concurrently...")
                    cookies_dict = session.cookies.get_dict()
                    
                    with ThreadPoolExecutor(max_workers=6) as executor:
                        results = list(executor.map(lambda j: fetch_job_detail(j, cookies_dict), jobs_to_check))
                        
                    for res in results:
                        if res and res.get("success"):
                            title = res["title"]
                            description = res["description"]
                            listing_location = res["location"]
                            detail_url = res["url"]
                            deadline = res["deadline"]
                            
                            if matches_profile(title, description, listing_location):
                                print(f"      => MATCH FOUND: '{title}' (Location: {listing_location})")
                                score, reason, reqs = get_ai_evaluation(title, description, listing_location, job_url=detail_url)
                                match = {
                                    "Platform": "Daleel Madani",
                                    "Title": title,
                                    "Location": listing_location,
                                    "Description": clean_description(description),
                                    "Deadline": deadline,
                                    "URL": detail_url,
                                    "Match Score": score,
                                    "Match Reason": reason,
                                    "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs
                                }
                                matched_jobs.append(match)
                                db.save_job(match)
                        else:
                            title = res.get("title", "Unknown")
                            err = res.get("error") or f"HTTP status {res.get('status')}"
                            print(f"      Failed checking detail for '{title}': {err}")
                            
                time.sleep(PAGE_DELAY)
            except Exception as e:
                print(f"    Error scraping search page {page_num + 1}: {e}")
            
    return matched_jobs

# --- EURAXESS Scraper ---
def scrape_euraxess(existing_urls=None):
    print("[EURAXESS] Initiating scraper...")
    if not KEYWORDS:
        print("[EURAXESS] No keywords configured. Skipping EURAXESS.")
        return []
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    }
    
    session = curl_requests.Session(impersonate="chrome")
    session.headers.update(headers)
    
    matched_jobs = []
    seen_urls = set()
    if existing_urls is None:
        existing_urls = set()
    
    def fetch_euraxess_detail(job):
        try:
            r = http_get_with_retry(job["url"], session=session, timeout=15, retries=4, backoff=3)
            if r.status_code == 200:
                detail_soup = BeautifulSoup(r.text, "html.parser")
                col_elem = detail_soup.select_one(".ecl-col-l-9")
                description = col_elem.text.strip() if col_elem else ""
                
                return {
                    "success": True,
                    "title": job["title"],
                    "location": job["location"],
                    "url": job["url"],
                    "description": description,
                    "deadline": job["deadline"]
                }
            else:
                return {"success": False, "title": job["title"], "status": r.status_code}
        except Exception as e:
            return {"success": False, "title": job["title"], "error": str(e)}
            
    from concurrent.futures import ThreadPoolExecutor
    
    for kw in KEYWORDS:
        print(f"\n[EURAXESS] Searching keyword: '{kw}'...")
        for page_num in range(2):
            url = f"https://euraxess.ec.europa.eu/jobs/search?f[0]=keywords:{kw}&page={page_num}"
            print(f"  Fetching page {page_num + 1}: {url}")
            
            try:
                r = http_get_with_retry(url, session=session, timeout=20)
                if r.status_code != 200:
                    print(f"    Failed to fetch page {page_num + 1}. Status: {r.status_code}")
                    break
                    
                soup = BeautifulSoup(r.text, "html.parser")
                items = soup.select(".ecl-content-item")
                print(f"    Found {len(items)} listings on page {page_num + 1}.")
                
                if not items:
                    break
                    
                jobs_to_check = []
                for item in items:
                    title_elem = item.select_one(".ecl-content-block__title a")
                    if not title_elem:
                        continue
                        
                    title = title_elem.text.strip()
                    href = title_elem.get("href", "")
                    detail_url = f"https://euraxess.ec.europa.eu{href}" if href.startswith("/") else href
                    
                    if detail_url in seen_urls:
                        continue
                    seen_urls.add(detail_url)
                    
                    if detail_url in existing_urls:
                        continue
                        
                    cached_job = db.get_cached_job(detail_url)
                    if cached_job:
                        print(f"    [Cache] Restored cached match details for: '{title}'")
                        cached_job["Status"] = "New"
                        db.save_job(cached_job)
                        matched_jobs.append(cached_job)
                        continue
                    
                    loc_elem = item.select_one(".id-Work-Locations .ecl-text-standard")
                    listing_location = loc_elem.text.strip() if loc_elem else "Europe"
                    
                    deadline_elem = item.select_one(".id-Application-Deadline time")
                    deadline = deadline_elem.text.strip() if deadline_elem else "N/A"
                    
                    jobs_to_check.append({
                        "title": title,
                        "url": detail_url,
                        "location": listing_location,
                        "deadline": deadline
                    })
                    
                if jobs_to_check:
                    print(f"    [EURAXESS] Checking {len(jobs_to_check)} details sequentially...")
                    results = []
                    for job_item in jobs_to_check:
                        res = fetch_euraxess_detail(job_item)
                        results.append(res)
                        time.sleep(1.5)  # rate limit bypass delay (safe sequential delay)
                        
                    for res in results:
                        if res and res.get("success"):
                            title = res["title"]
                            description = res["description"]
                            listing_location = res["location"]
                            detail_url = res["url"]
                            deadline = res["deadline"]
                            
                            if matches_profile(title, description, listing_location):
                                print(f"      => MATCH FOUND: '{title}' (Location: {listing_location})")
                                score, reason, reqs = get_ai_evaluation(title, description, listing_location, job_url=detail_url)
                                match = {
                                    "Platform": "EURAXESS",
                                    "Title": title,
                                    "Location": listing_location,
                                    "Description": clean_description(description),
                                    "Deadline": deadline,
                                    "URL": detail_url,
                                    "Match Score": score,
                                    "Match Reason": reason,
                                    "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs
                                }
                                matched_jobs.append(match)
                                db.save_job(match)
                        else:
                            title = res.get("title", "Unknown")
                            err = res.get("error") or f"HTTP status {res.get('status')}"
                            print(f"      Failed checking detail for '{title}': {err}")
                            
                time.sleep(PAGE_DELAY)
            except Exception as e:
                print(f"    Error scraping search page {page_num + 1}: {e}")
        time.sleep(3.0)  # Sleep between keyword searches to prevent rate limiting
                
    return matched_jobs

# --- UN Careers Scraper (Dynamic) ---
def perform_un_login(page, username, password):
    """
    Performs login inputs and submissions on UN Inspira login form
    """
    print("[UN Careers] Login form detected. Entering credentials...")
    username_selectors = ["input#userid", "input[name='userid']", "input#USER_ID", "input[name='USER_ID']", "input[id*='USER_ID']"]
    password_selectors = ["input#pwd", "input[name='pwd']", "input[id*='pwd']"]
    
    # Fill username
    username_filled = False
    for sel in username_selectors:
        if page.locator(sel).is_visible():
            page.fill(sel, username)
            username_filled = True
            break
            
    if not username_filled:
        raise Exception("Could not find the username input field.")
        
    # Fill password
    password_filled = False
    for sel in password_selectors:
        if page.locator(sel).is_visible():
            page.fill(sel, password)
            password_filled = True
            break
            
    if not password_filled:
        raise Exception("Could not find the password input field.")
        
    # Click Submit
    login_buttons = ["input#login", "input[type='submit']", "button[type='submit']", "input[value='Login']"]
    submit_clicked = False
    for btn in login_buttons:
        if page.locator(btn).is_visible():
            page.click(btn)
            submit_clicked = True
            break
            
    if not submit_clicked:
        page.keyboard.press("Enter")
        
    print("[UN Careers] Login submitted. Waiting for page redirection...")
    page.wait_for_load_state("networkidle")
    time.sleep(5)

def scrape_un_careers(existing_urls=None):
    """
    Scrapes job listings from UN Inspira portal
    """
    print(f"\n--- [UN Careers] Launching Playwright to scrape UN Careers (Inspira) (Headless={HEADLESS}) ---")
    username = UN_USERNAME
    password = UN_PASSWORD
    
    matched_jobs = []
    state_file = "storage_state.json"
    if existing_urls is None:
        existing_urls = set()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        
        # Load state if exists
        if os.path.exists(state_file):
            print(f"[UN Careers] Loading session state from {state_file}...")
            context = browser.new_context(
                storage_state=state_file,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
        else:
            print("[UN Careers] No storage state found. Fresh browser context.")
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            print("[UN Careers] Navigating to https://inspira.un.org...")
            page.goto("https://inspira.un.org", wait_until="domcontentloaded", timeout=60000)
            time.sleep(4)
            
            title = page.title()
            print(f"[UN Careers] Page Title: '{title}'")
            
            # Wait up to 10 seconds for either login fields or dashboard elements to render
            is_login_page = False
            try:
                page.wait_for_selector("input#userid, input#pwd, input#USER_ID, a:has-text('Search Jobs')", timeout=10000)
                if page.locator("input#userid, input#USER_ID").first.is_visible():
                    is_login_page = True
            except Exception:
                pass

            if is_login_page:
                if username and password and "your_un" not in username:
                    perform_un_login(page, username, password)
                    
                    # Verify if login succeeded
                    time.sleep(5)
                    if page.locator("input#userid, input#USER_ID").first.is_visible() or "errorCode" in page.url:
                        print("[UN Careers] Error: Login failed. Please check your credentials in settings.json. Skipping UN Careers.")
                        browser.close()
                        return []
                        
                    print(f"[UN Careers] Login succeeded. Saving storage state to {state_file}...")
                    context.storage_state(path=state_file)
                else:
                    print("[UN Careers] Login is required but real credentials are not set in settings.json. Skipping UN Careers.")
                    browser.close()
                    return []
            else:
                print("[UN Careers] Session state bypassed the login portal.")
            
            # Check and dismiss the Language Framework popup modal if it exists
            time.sleep(3)
            try:
                modal_frame = page.frame_locator("#ptModFrame_0")
                ok_btn = modal_frame.locator("input[value='OK'], button:has-text('OK'), #OK").first
                if ok_btn.is_visible():
                    print("[UN Careers] Dismissing Language Profile popup modal...")
                    ok_btn.click()
                    time.sleep(6)
            except Exception as me:
                print(f"[UN Careers] Note: No popup modal processed: {me}")
            
            # Accessing the Job Search elements
            print("[UN Careers] Accessing Job Search interface...")
            
            # Extract site name dynamically from current page URL (usually PUNA1J or UNCAREERS)
            current_url = page.url
            site_name = "PUNA1J"
            for term in ["/psc/", "/psp/"]:
                if term in current_url:
                    parts = current_url.split(term)
                    if len(parts) > 1:
                        site_name = parts[1].split("/")[0]
                        break
            
            # Navigate directly to the applicant search page
            search_url = f"https://inspira.un.org/psp/{site_name}/EMPLOYEE/HRMS/c/HRS_HRAM.HRS_APP_SCHJOB.GBL"
            print(f"[UN Careers] Direct URL navigation: {search_url}...")
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)

            # Session-expiry guard: if we got bounced back to login, re-authenticate once
            try:
                if page.locator("input#userid, input#USER_ID").first.is_visible():
                    print("[UN Careers] Session expired mid-run. Attempting re-login...")
                    if username and password and "your_un" not in username:
                        perform_un_login(page, username, password)
                        time.sleep(5)
                        if page.locator("input#userid, input#USER_ID").first.is_visible():
                            print("[UN Careers] Re-login failed. Skipping UN Careers.")
                            browser.close()
                            return []
                        print("[UN Careers] Re-login succeeded. Re-saving storage state...")
                        context.storage_state(path=state_file)
                        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                        time.sleep(5)
                    else:
                        print("[UN Careers] Cannot re-login — credentials not set. Skipping.")
                        browser.close()
                        return []
            except Exception as se:
                print(f"[UN Careers] Session-expiry check error (non-fatal): {se}")

            # Support PeopleSoft frame target structure
            frame_exists = page.locator("#ptifrmtgtframe").is_visible()
            target = page.frame_locator("#ptifrmtgtframe") if frame_exists else page
            
            # Try to change Posted Within to Anytime for broader search
            try:
                posted_wtn = target.locator("#HRS_SCH_WRK_HRS_POSTED_WTN")
                posted_wtn.wait_for(timeout=15000)
                if posted_wtn.is_visible():
                    print("[UN Careers] Selecting 'Anytime' for Posted Within...")
                    posted_wtn.select_option("A")
                    time.sleep(2)
            except Exception as de:
                print(f"[UN Careers] Note: Could not set posted within dropdown: {de}")
            
            # Find the search button
            search_submit = target.locator("input[name='SEARCHACTIONS#SEARCH'], input[value*='Search'], button:has-text('Search')").first
            
            try:
                search_submit.wait_for(timeout=15000)
            except Exception:
                pass
                
            if search_submit.is_visible():
                print("[UN Careers] Clicking Search button...")
                search_submit.click()
                time.sleep(12)  # Let results load
            else:
                page.screenshot(path="un_search_button_not_found.png")
                print("[UN Careers] Search button not visible. Screenshot saved to un_search_button_not_found.png. Skipping search.")
                browser.close()
                return []
            
            # Scan up to 4 pages (100 jobs) on UN Careers
            current_page = 1
            max_pages = 4
            
            while current_page <= max_pages:
                grid_rows = target.locator("tr.PSLEVEL1GRIDROW, tr.PSLEVEL1GRIDODDROW, tr[id^='trHRS_AGNT_RSLT_I'], table.PSLEVEL1GRID tr[id*='row']").all()
                print(f"[UN Careers] Page {current_page}: Found {len(grid_rows)} job listings on the page.")
                if not grid_rows:
                    break
                    
                for idx in range(len(grid_rows)):
                    try:
                        # Refetch rows fresh on each iteration
                        current_rows = target.locator("tr.PSLEVEL1GRIDROW, tr.PSLEVEL1GRIDODDROW, tr[id^='trHRS_AGNT_RSLT_I'], table.PSLEVEL1GRID tr[id*='row']").all()
                        if idx >= len(current_rows):
                            break
                        row = current_rows[idx]
                        
                        # Identify Job title element and location element in row columns
                        title_link = row.locator("a[id*='UN_JOB_TITLE'], a[id*='POSTINGLINK'], a[id*='LINK'], a[id*='TITLE']").first
                        if not title_link.is_visible():
                            continue
                            
                        title = title_link.text_content().strip()
                        
                        location_elem = row.locator("span[id*='DUTY_STATION'], span[id*='LOCATION'], span[id*='DESCR']").first
                        location = location_elem.text_content().strip() if location_elem.is_visible() else "N/A"
                        
                        # If location not found in column element, try parsing row text
                        row_text = row.text_content()
                        if location == "N/A" or not location:
                            for loc in LOCATIONS:
                                if loc.lower() in row_text.lower():
                                    location = loc
                                    break
                        
                        # Pre-filtering optimization: only click details if title or location matches
                        title_lower = title.lower()
                        row_text_lower = row_text.lower()
                        has_kw_match = any(kw.lower() in title_lower for kw in KEYWORDS)
                        has_loc_match = any(loc.lower() in row_text_lower for loc in LOCATIONS)
                        
                        if not has_kw_match and not has_loc_match:
                            continue
                        
                        print(f"  Checking details for Job {idx+1}/{len(grid_rows)}: '{title}' (Location: {location})")
                        
                        # Extract JobOpeningId to use direct deep-linking
                        import re
                        job_id_match = re.search(r"-\s*([0-9]+)$", title.strip())
                        
                        detail_url = ""
                        description = ""
                        deadline = "N/A"
                        detail_page = None
                        
                        if job_id_match:
                            job_id = job_id_match.group(1)
                            detail_url = f"https://inspira.un.org/psp/PUNA1J/EMPLOYEE/HRMS/c/HRS_HRAM.HRS_APP_SCHJOB.GBL?Page=HRS_APP_JBPST&Action=U&FOCUS=Applicant&JobOpeningId={job_id}&SiteId=1&PostingSeq=1"
                            if detail_url in existing_urls:
                                print(f"    [Skip] Already tracked: '{title}'")
                                continue
                                
                            cached_job = db.get_cached_job(detail_url)
                            if cached_job:
                                print(f"    [Cache] Restored cached match details for: '{title}'")
                                cached_job["Status"] = "New"
                                db.save_job(cached_job)
                                matched_jobs.append(cached_job)
                                continue
                            try:
                                # Open a new page in the same context to fetch details fast
                                detail_page = context.new_page()
                                detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
                                frame_exists = detail_page.locator("#ptifrmtgtframe").is_visible()
                                detail_target = detail_page.frame_locator("#ptifrmtgtframe") if frame_exists else detail_page
                                detail_target.locator("body").wait_for(state="visible", timeout=20000)
                                try:
                                    detail_target.locator("span[id*='TITLE'], input[type='button'][value='Back']").first.wait_for(state="visible", timeout=10000)
                                except Exception:
                                    pass
                                time.sleep(1)
                                description = detail_target.locator("body").text_content()
                            except Exception as de:
                                print(f"    Failed deep-linking to Job ID {job_id}: {de}")
                                if detail_page:
                                    try: detail_page.close()
                                    except Exception: pass
                                detail_page = None
                                
                        # Fallback to sequential click navigation if deep-link failed or not applicable
                        if not description:
                            title_link.click()
                            time.sleep(5)
                            frame_exists = page.locator("#ptifrmtgtframe").is_visible()
                            target = page.frame_locator("#ptifrmtgtframe") if frame_exists else page
                            description = target.locator("body").text_content()
                            detail_url = page.url
                            
                        # Check profile match
                        if matches_profile(title, description, location):
                            print(f"    => MATCH FOUND: '{title}'")
                            period_match = re.search(r"Posting Period\s*:\s*[0-9a-zA-Z\s\/]+\s*-\s*([^\n\r]+)", description)
                            if period_match:
                                deadline = period_match.group(1).strip()
                                
                            score, reason, reqs = get_ai_evaluation(title, description, location, job_url=detail_url)
                            match = {
                                "Platform": "UN Careers",
                                "Title": title,
                                "Location": location,
                                "Description": clean_description(description),
                                "Deadline": deadline,
                                "URL": detail_url,
                                "Match Score": score,
                                "Match Reason": reason,
                                "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs
                            }
                            matched_jobs.append(match)
                            db.save_job(match)
                        else:
                            print("    No profile match.")
                            
                        # Cleanup detail page or return main page back
                        if detail_page:
                            try:
                                detail_page.close()
                            except Exception:
                                pass
                        else:
                            # sequential click fallback cleanup: return back
                            back_btn = target.locator("a:has-text('Return to Previous Page'), a:has-text('Back'), input[type='button'][value='Back'], button:has-text('Back')").first
                            if back_btn.is_visible():
                                back_btn.click()
                                try:
                                    target.locator("tr.PSLEVEL1GRIDROW, tr.PSLEVEL1GRIDODDROW").first.wait_for(state="visible", timeout=15000)
                                except Exception:
                                    pass
                            else:
                                print("    Back button not found. Reloading search page and re-executing search...")
                                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                                time.sleep(5)
                                search_btn = target.locator("input[name='SEARCHACTIONS#SEARCH']").first
                                search_btn.click()
                                time.sleep(10)
                            # Recover page state
                            if current_page > 1:
                                select_el = target.locator("select[id*='hpage']").first
                                if select_el.is_visible():
                                    val = str((current_page - 1) * 25)
                                    select_el.select_option(val)
                                    time.sleep(8)
                                    
                    except Exception as re:
                        print(f"    Error parsing listing row: {re}")
                
                # Navigate to next page
                current_page += 1
                if current_page <= max_pages:
                    select_el = target.locator("select[id*='hpage']").first
                    if select_el.is_visible():
                        val = str((current_page - 1) * 25)
                        print(f"[UN Careers] Selecting next page option {current_page} (value: {val})...")
                        select_el.select_option(val)
                        time.sleep(8)
                    else:
                        print("[UN Careers] Dropdown pagination not found. Stopping pagination.")
                        break
                    
        except Exception as e:
            print(f"[UN Careers] Dynamic scraping error: {e}")
            try:
                page.screenshot(path="un_scraper_error.png")
                print("Screenshot saved to un_scraper_error.png")
            except Exception as se:
                print(f"Could not save error screenshot: {se}")
        finally:
            browser.close()
            
    return matched_jobs

# --- ReliefWeb Scraper ---
def scrape_reliefweb(existing_urls=None):
    # Map target locations/cities to country names for ReliefWeb search engine
    CITY_TO_COUNTRY = {
        "beirut": "Lebanon",
        "paris": "France",
        "berlin": "Germany",
        "hamburg": "Germany"
    }
    
    countries = set()
    for loc in LOCATIONS:
        loc_lower = loc.lower()
        if loc_lower in CITY_TO_COUNTRY:
            countries.add(CITY_TO_COUNTRY[loc_lower])
        else:
            # Fallback capitalization
            countries.add(loc.capitalize())
            
    if countries:
        query_str = " OR ".join(f"country:{c}" for c in countries)
    else:
        query_str = "country:Lebanon"
        
    print(f"\n--- [ReliefWeb] Scraping jobs matching target countries: {', '.join(countries)} ---")
    matched_jobs = []
    if existing_urls is None:
        existing_urls = set()

    params = {"search": query_str}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/120.0.0.0"
    }
    
    url = "https://reliefweb.int/jobs"

    try:
        r = http_get_with_retry(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"[ReliefWeb] Failed to load list: status code {r.status_code}")
            return []
            
        soup = BeautifulSoup(r.text, "html.parser")
        listings = soup.select(".rw-river-article")
        print(f"[ReliefWeb] Found {len(listings)} active jobs in target countries.")
        
        for idx, item in enumerate(listings[:15]):  # check up to 15 jobs
            try:
                title_el = item.select_one(".rw-river-article__title a")
                if not title_el:
                    continue
                title = title_el.text.strip()
                detail_url = title_el.get("href")
                if not detail_url.startswith("http"):
                    detail_url = f"https://reliefweb.int{detail_url}"

                if detail_url in existing_urls:
                    print(f"  [Skip] Already tracked: '{title}'")
                    continue
                    
                cached_job = db.get_cached_job(detail_url)
                if cached_job:
                    print(f"  [Cache] Restored cached match details for: '{title}'")
                    cached_job["Status"] = "New"
                    db.save_job(cached_job)
                    matched_jobs.append(cached_job)
                    continue
                    
                # Extract country
                country_el = item.select_one(".rw-entity-country-slug__link")
                country = country_el.text.strip() if country_el else "Lebanon"
                
                print(f"  Checking details for Job {idx+1}/{len(listings)}: '{title}'...")
                
                dr = http_get_with_retry(detail_url, headers=headers, timeout=15)
                if dr.status_code == 200:
                    detail_soup = BeautifulSoup(dr.text, "html.parser")
                    # Extract description from the actual content container to avoid sidebar/footer false positives
                    desc_elem = detail_soup.select_one(".rw-article__content")
                    if not desc_elem:
                        desc_elem = detail_soup.select_one("article")
                    description = desc_elem.text.strip() if desc_elem else detail_soup.get_text()
                    
                    if matches_profile(title, description, country):
                        print(f"    => MATCH FOUND: '{title}'")
                        closing_el = detail_soup.select_one(".rw-entity-meta__tag-value--closing")
                        deadline = closing_el.text.strip() if closing_el else "N/A"
                        
                        score, reason, reqs = get_ai_evaluation(title, description, country, job_url=detail_url)
                        match = {
                            "Platform": "ReliefWeb",
                            "Title": title,
                            "Location": country,
                            "Description": clean_description(description),
                            "Deadline": deadline,
                            "URL": detail_url,
                            "Match Score": score,
                            "Match Reason": reason,
                            "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs
                        }
                        matched_jobs.append(match)
                        db.save_job(match)
                    else:
                        print("    No profile match in details.")
                else:
                    print(f"    Failed to load details: status {dr.status_code}")
                    
                time.sleep(1)  # polite delay
            except Exception as ie:
                print(f"  Error parsing ReliefWeb row: {ie}")
    except Exception as e:
        print(f"[ReliefWeb] Scraping failed: {e}")
        
    return matched_jobs

# --- LinkedIn Scraper ---
def scrape_linkedin(existing_urls=None):
    print("\n--- [LinkedIn] Scraping public listings (using guest API) ---")
    matched_jobs = []
    if existing_urls is None:
        existing_urls = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/120.0.0.0"
    }
    
    combined_kws = " OR ".join(f'"{kw}"' for kw in KEYWORDS)

    # If no locations configured, run a single global search
    search_locations = LOCATIONS if LOCATIONS else [""]

    for loc in search_locations:
        loc_label = loc if loc else "(global)"
        print(f"  Searching LinkedIn for '{combined_kws}' in '{loc_label}'...")
        params = {
            "keywords": combined_kws,
            "start": 0
        }
        if loc:
            params["location"] = loc
        
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        try:
            r = http_get_with_retry(url, params=params, headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"    Failed to query LinkedIn for {loc}: status {r.status_code}")
                continue
                
            soup = BeautifulSoup(r.text, "html.parser")
            listings = soup.select("li")
            print(f"    Found {len(listings)} listings in '{loc}'.")
            
            for idx, item in enumerate(listings[:10]):  # check top 10 listings per location
                try:
                    title_el = item.select_one(".base-search-card__title")
                    company_el = item.select_one(".base-search-card__subtitle a")
                    loc_el = item.select_one(".job-search-card__location")
                    link_el = item.select_one(".base-card__full-link")

                    if not title_el or not link_el:
                        continue

                    # Extract post date for LinkedIn (since there is no application deadline)
                    date_el = item.select_one("time, .job-search-card__listdate, .job-search-card__listdate--new")
                    post_date = date_el.text.strip() if date_el else ""
                    deadline_str = f"Posted: {post_date}" if post_date else "See listing"

                    title = title_el.text.strip()
                    company = company_el.text.strip() if company_el else "N/A"
                    location = loc_el.text.strip() if loc_el else loc
                    detail_url = link_el.get("href")

                    if "?" in detail_url:
                        detail_url = detail_url.split("?")[0]

                    if detail_url in existing_urls:
                        print(f"    [Skip] Already tracked: '{title}'")
                        continue
                        
                    cached_job = db.get_cached_job(detail_url)
                    if cached_job:
                        full_title = f"{title} at {company}" if company != "N/A" else title
                        print(f"    [Cache] Restored cached match details for: '{full_title}'")
                        cached_job["Status"] = "New"
                        db.save_job(cached_job)
                        matched_jobs.append(cached_job)
                        continue

                    full_title = f"{title} at {company}" if company != "N/A" else title

                    # Fetch real description from the detail page
                    description = f"Active position at {company} in {location}. Open link for full requirements."
                    try:
                        dr = http_get_with_retry(detail_url, headers=headers, timeout=15)
                        if dr.status_code == 200:
                            detail_soup = BeautifulSoup(dr.text, "html.parser")
                            desc_elem = (
                                detail_soup.select_one(".description__text") or
                                detail_soup.select_one(".show-more-less-html__markup") or
                                detail_soup.select_one("section.description")
                            )
                            if desc_elem:
                                description = desc_elem.get_text(separator=" ", strip=True)
                    except Exception as fe:
                        print(f"    Warning: could not fetch LinkedIn detail for '{full_title}': {fe}")

                    if not matches_profile(full_title, description, location):
                        print(f"    Skipping '{full_title}' — no profile match.")
                        continue

                    print(f"    => MATCH FOUND: '{full_title}'")

                    score, reason, reqs = get_ai_evaluation(full_title, description, location, job_url=detail_url)
                    match = {
                        "Platform": "LinkedIn",
                        "Title": full_title,
                        "Location": location,
                        "Description": clean_description(description),
                        "Deadline": deadline_str,
                        "URL": detail_url,
                        "Match Score": score,
                        "Match Reason": reason,
                        "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs
                    }
                    matched_jobs.append(match)
                    db.save_job(match)

                except Exception as ie:
                    print(f"    Error parsing row: {ie}")
            time.sleep(1)  # polite delay between location queries
        except Exception as e:
            print(f"    Error querying LinkedIn for {loc}: {e}")
            
    return matched_jobs

# --- Bayt.com Scraper ---
def scrape_bayt(existing_urls=None):
    print("\n--- [Bayt.com] Launching HTTP Scraper via curl_cffi ---")
    from curl_cffi import requests
    matched_jobs = []
    if existing_urls is None:
        existing_urls = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    session = curl_requests.Session(impersonate="chrome")
    session.headers.update(headers)

    search_locations = LOCATIONS if LOCATIONS else ["lebanon"]

    # Map cities/locations to their country counterparts for Bayt's URL structure to avoid 404
    CITY_TO_COUNTRY_BAYT = {
        "beirut": "lebanon",
        "paris": "france",
        "berlin": "germany",
        "hamburg": "germany"
    }

    for loc in search_locations:
        loc_slug = CITY_TO_COUNTRY_BAYT.get(loc.lower(), loc.lower()).replace(' ', '-')
        for kw in KEYWORDS:
            url = f"https://www.bayt.com/en/{loc_slug}/jobs/?q={kw}"
            print(f"  [Bayt.com] Querying: {url}...")

            try:
                r = http_get_with_retry(url, session=session, timeout=15)
                if r.status_code != 200:
                    print(f"    Failed to retrieve Bayt page for '{kw}' in '{loc}': Status {r.status_code}")
                    continue

                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select("li[data-js-job]")
                print(f"  [Bayt.com] Found {len(cards)} listings for '{kw}' in '{loc}'.")

                for card in cards:
                    try:
                        title_link = card.select_one("a")
                        if not title_link:
                            continue
                        title = title_link.text.strip()
                        href = title_link.get("href") or ""
                        detail_url = f"https://www.bayt.com{href}" if href.startswith("/") else href

                        company_el = card.select_one(".job-company-location-wrapper a.t-default.t-bold")
                        company = company_el.text.strip() if company_el else "N/A"
                        
                        if detail_url in existing_urls:
                            print(f"    [Skip] Already tracked: '{title}'")
                            continue
                            
                        cached_job = db.get_cached_job(detail_url)
                        if cached_job:
                            full_title = f"{title} at {company}" if company != "N/A" else title
                            print(f"    [Cache] Restored cached match details for: '{full_title}'")
                            cached_job["Status"] = "New"
                            db.save_job(cached_job)
                            matched_jobs.append(cached_job)
                            continue
                        
                        loc_el = card.select_one(".job-company-location-wrapper div.t-mute")
                        location = loc_el.text.strip() if loc_el else loc
                        
                        card_text = card.get_text()
                        description = ""
                        if "Summary:" in card_text:
                            description = card_text.split("Summary:")[1].split("\n")[0].strip()
                        if not description:
                            description = card_text.strip()
                            
                        full_title = f"{title} at {company}" if company != "N/A" else title

                        # Bayt pre-filters by keyword via search URL, but we apply our own logic to be sure.
                        if not matches_profile(full_title, description, location):
                            continue

                        print(f"    => MATCH FOUND: '{full_title}'")

                        date_el = card.select_one(".jb-date")
                        deadline = f"Posted: {date_el.text.strip()}" if date_el else "See listing"

                        score, reason, reqs = get_ai_evaluation(full_title, description, location, job_url=detail_url)
                        match = {
                            "Platform": "Bayt.com",
                            "Title": full_title,
                            "Location": location,
                            "Description": clean_description(description),
                            "Deadline": deadline,
                            "URL": detail_url,
                            "Match Score": score,
                            "Match Reason": reason,
                            "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs
                        }
                        matched_jobs.append(match)
                        db.save_job(match)
                    except Exception as ce:
                        print(f"    Error parsing card: {ce}")
                time.sleep(1)  # polite delay between keyword queries
            except Exception as e:
                print(f"    Error loading Bayt page for '{kw}' in '{loc}': {e}")
            
    return matched_jobs

# --- Main Pipeline ---
def run_pipeline():
    print("====================================================")
    print("STARTING PROFILE-MATCHED JOB SCRAPER PIPELINE")
    print("====================================================")

    # Clear old "New" matches from the database, keeping Applied/Archived
    try:
        db.prepare_new_scan()
        print("[Pipeline] Successfully prepared database for new scan.")
    except Exception as ex:
        print(f"[Pipeline] Error preparing database: {ex}")

    # Load already-tracked URLs once so all scrapers can skip them
    existing_urls = load_existing_urls()
    print(f"[Pipeline] {len(existing_urls)} URLs already tracked — will skip these.")

    
    def run_daleel():
        if "Daleel Madani" in PLATFORMS:
            import threading
            daleel_jobs = []
            def worker():
                nonlocal daleel_jobs
                try:
                    daleel_jobs = scrape_daleel_madani()
                except Exception as we:
                    print(f"[Daleel Madani] Worker error: {we}")
            t = threading.Thread(target=worker)
            t.daemon = True
            print("[Daleel Madani] Initiating scraper thread...")
            t.start()
            t.join(180)
            if t.is_alive():
                print("\n[Daleel Madani] Scraper thread timed out. Skipping.")
            else:
                print(f"\n[Daleel Madani] Completed scraping. Found {len(daleel_jobs)} matches.")
        else:
            print("\n[Daleel Madani] Skipping (disabled in configuration).")
            
    def run_un():
        if "UN Careers" in PLATFORMS:
            import threading
            un_jobs = []
            def worker():
                nonlocal un_jobs
                try:
                    un_jobs = scrape_un_careers(existing_urls=existing_urls)
                except Exception as we:
                    print(f"[UN Careers] Worker error: {we}")
            t = threading.Thread(target=worker)
            t.daemon = True
            print("[UN Careers] Initiating scraper thread (timeout: 300s)...")
            t.start()
            t.join(300)
            if t.is_alive():
                print("\n[UN Careers] Scraper thread timed out after 300s. Skipping.")
            else:
                print(f"\n[UN Careers] Completed scraping. Found {len(un_jobs)} matches.")
        else:
            print("\n[UN Careers] Skipping (disabled in configuration).")
            
    def run_reliefweb():
        if "ReliefWeb" in PLATFORMS:
            try:
                jobs = scrape_reliefweb(existing_urls=existing_urls)
                print(f"\n[ReliefWeb] Completed scraping. Found {len(jobs)} matches.")
            except Exception as e:
                print(f"\n[ReliefWeb] Scraper failed: {e}")
        else:
            print("\n[ReliefWeb] Skipping (disabled in configuration).")
            
    def run_linkedin():
        if "LinkedIn" in PLATFORMS:
            try:
                jobs = scrape_linkedin(existing_urls=existing_urls)
                print(f"\n[LinkedIn] Completed scraping. Found {len(jobs)} matches.")
            except Exception as e:
                print(f"\n[LinkedIn] Scraper failed: {e}")
        else:
            print("\n[LinkedIn] Skipping (disabled in configuration).")

    def run_bayt():
        if "Bayt.com" in PLATFORMS:
            try:
                jobs = scrape_bayt(existing_urls=existing_urls)
                print(f"\n[Bayt.com] Completed scraping. Found {len(jobs)} matches.")
            except Exception as e:
                print(f"\n[Bayt.com] Scraper failed: {e}")
        else:
            print("\n[Bayt.com] Skipping (disabled in configuration).")

    def run_euraxess():
        if "EURAXESS" in PLATFORMS:
            try:
                jobs = scrape_euraxess(existing_urls=existing_urls)
                print(f"\n[EURAXESS] Completed scraping. Found {len(jobs)} matches.")
            except Exception as e:
                print(f"\n[EURAXESS] Scraper failed: {e}")
        else:
            print("\n[EURAXESS] Skipping (disabled in configuration).")

    def run_oea():
        if "OEA" in PLATFORMS:
            try:
                jobs = scrape_oea(existing_urls=existing_urls)
                print(f"\n[OEA Beirut] Completed scraping. Found {len(jobs)} matches.")
            except Exception as e:
                print(f"\n[OEA Beirut] Scraper failed: {e}")
        else:
            print("\n[OEA] Skipping (disabled in configuration).")

    def run_jobs_for_lebanon():
        if "Jobs for Lebanon" in PLATFORMS:
            try:
                jobs = scrape_jobs_for_lebanon(existing_urls=existing_urls)
                print(f"\n[Jobs for Lebanon] Completed scraping. Found {len(jobs)} matches.")
            except Exception as e:
                print(f"\n[Jobs for Lebanon] Scraper failed: {e}")
        else:
            print("\n[Jobs for Lebanon] Skipping (disabled in configuration).")

    # Start threads concurrently
    import threading
    t_daleel = threading.Thread(target=run_daleel)
    t_un = threading.Thread(target=run_un)
    t_rw = threading.Thread(target=run_reliefweb)
    t_li = threading.Thread(target=run_linkedin)
    t_bayt = threading.Thread(target=run_bayt)
    t_euraxess = threading.Thread(target=run_euraxess)
    t_oea = threading.Thread(target=run_oea)
    t_jfl = threading.Thread(target=run_jobs_for_lebanon)
    
    t_daleel.daemon = True
    t_un.daemon = True
    t_rw.daemon = True
    t_li.daemon = True
    t_bayt.daemon = True
    t_euraxess.daemon = True
    t_oea.daemon = True
    t_jfl.daemon = True
    
    t_daleel.start()
    t_un.start()
    t_rw.start()
    t_li.start()
    t_bayt.start()
    t_euraxess.start()
    t_oea.start()
    t_jfl.start()
    
    t_daleel.join()
    t_un.join()
    t_rw.join()
    t_li.join()
    t_bayt.join()
    t_euraxess.join()
    t_oea.join()
    t_jfl.join()
    
    # Deduplicate final database entries and export to CSV
    print("\n====================================================")
    print("PIPELINE EXECUTION COMPLETE")
    print("====================================================")
    try:
        df = db.get_all_jobs_df()
        print(f"Total matching jobs found: {len(df)}")
        print(df.to_string())
    except Exception as ex:
        print(f"Error fetching database results: {ex}")


def scrape_custom_office_website(office_name, website_url):
    """
    Crawls the website of a custom office, searches for careers information,
    and uses Gemini to extract open job roles.
    """
    import pandas as pd
    import json
    import requests
    from bs4 import BeautifulSoup
    
    print(f"\n--- [AI Web Scraper] Scanning website for '{office_name}' at: {website_url} ---")
    
    if not website_url or pd.isna(website_url) or not isinstance(website_url, str):
        return {"success": False, "error": "Invalid website URL."}
        
    url = website_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    if not GEMINI_API_KEY:
        return {"success": False, "error": "Gemini API key is required to use the website AI scraper."}

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive"
    }

    # Fetch main homepage
    try:
        r = http_get_with_retry(url, headers=headers, timeout=15, retries=2, backoff=2)
        if r.status_code != 200:
            return {"success": False, "error": f"Failed to fetch homepage: HTTP status {r.status_code}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to connect to website: {e}"}

    soup = BeautifulSoup(r.text, "html.parser")
    
    # 1. Discover potential career links on the homepage
    candidate_urls = [url]  # Always scan main page as fallback
    
    from urllib.parse import urljoin
    for link_el in soup.find_all("a", href=True):
        href = link_el["href"].lower()
        text = link_el.get_text().lower()
        if href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("#"):
            continue
        if any(kw in href or kw in text for kw in ["career", "job", "vacancy", "work-with-us", "recruitment", "join", "contact", "about"]):
            absolute_url = urljoin(url, link_el["href"])
            if absolute_url.startswith("http://") or absolute_url.startswith("https://"):
                if absolute_url not in candidate_urls:
                    candidate_urls.append(absolute_url)

    # Let's inspect at most the first 3 candidate URLs to keep execution fast and polite
    scanned_pages = []
    
    # We prioritize sub-pages that are not the home page itself if they exist
    sub_pages = [p for p in candidate_urls if p != url][:2]
    pages_to_scan = sub_pages if sub_pages else [url]
    
    for page_url in pages_to_scan:
        try:
            print(f"  Fetching content page: {page_url}")
            pr = http_get_with_retry(page_url, headers=headers, timeout=12, retries=2, backoff=2)
            if pr.status_code == 200:
                page_soup = BeautifulSoup(pr.text, "html.parser")
                # Remove header/footer noise if possible, or just extract visible text
                for noise in page_soup(["script", "style", "nav", "footer"]):
                    noise.decompose()
                page_text = page_soup.get_text(separator=" ", strip=True)
                # Keep first 6000 chars
                page_text = page_text[:6000]
                scanned_pages.append({"url": page_url, "text": page_text})
        except Exception as e:
            print(f"  Warning: failed to fetch subpage {page_url}: {e}")

    if not scanned_pages:
        return {"success": False, "error": "No readable content pages found."}

    # Use Gemini to parse text from all scanned pages
    combined_text = "\n\n--- Page Content ---\n".join(f"URL: {p['url']}\n{p['text']}" for p in scanned_pages)
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""You are an expert recruiter scanning the website text of '{office_name}' (an architecture/design studio).
Analyze the page text below and determine if they list any active open vacancies or job openings.

Combine similar entries and exclude old or closed postings if explicitly indicated.

Respond ONLY with a JSON array of objects representing the open roles (no markdown code blocks, no backticks, just raw JSON). If no open roles are listed, return an empty array [].

Each object in the array MUST have this format:
{{
  "title": "Job Title (e.g. Architect, Intern)",
  "location": "Location (e.g. Beirut, Dbayeh)",
  "description": "Short summary of the role, requirements, or how to apply",
  "url": "Specific application/contact URL or email address"
}}

Page Text Content:
{combined_text}"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }

    try:
        ar = requests.post(api_url, headers=headers, json=payload, timeout=20)
        if ar.status_code != 200:
            return {"success": False, "error": f"Gemini API returned status {ar.status_code}"}
            
        res_json = ar.json()
        text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
        
        import re
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)
            
        roles = json.loads(text)
        if not isinstance(roles, list):
            roles = []
            
        matches_found = []
        for role in roles:
            title = role.get("title", "Job Posting")
            loc = role.get("location", "Beirut, Lebanon")
            desc = role.get("description", "No description provided.")
            job_url = role.get("url", url)
            
            # Match against user filters
            if matches_profile(title, desc, loc):
                # Perform AI evaluation (if enabled)
                score, reason, reqs = get_ai_evaluation(title, desc, loc, job_url=job_url)
                match = {
                    "Platform": office_name,
                    "Title": title,
                    "Location": loc,
                    "Description": clean_description(desc),
                    "Deadline": "See listing",
                    "URL": job_url,
                    "Match Score": score,
                    "Match Reason": reason,
                    "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs,
                    "Status": "New"
                }
                db.save_job(match)
                matches_found.append(match)
                
        return {"success": True, "roles": matches_found}
    except Exception as e:
        return {"success": False, "error": f"Error parsing website roles with Gemini: {e}"}

def decode_cf_email(cf_string):
    try:
        key = int(cf_string[:2], 16)
        email = "".join([chr(int(cf_string[i:i+2], 16) ^ key) for i in range(2, len(cf_string), 2)])
        return email
    except Exception:
        return ""

def scrape_oea(existing_urls=None):
    """
    Scrapes the Order of Engineers and Architects (OEA) Beirut job portal.
    Bypasses 403 Forbidden utilizing curl_cffi and extracts/decodes details of
    relevant architectural/planning roles.
    """
    import urllib.parse
    from bs4 import BeautifulSoup
    from curl_cffi import requests
    import re
    
    print("\n--- [OEA Beirut] Initiating scraper... ---")
    if existing_urls is None:
        existing_urls = []
        
    url = "https://www.oea.org.lb/career/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive"
    }

    # Fetch main career page
    try:
        r = requests.get(url, headers=headers, impersonate="chrome120", timeout=20)
        if r.status_code != 200:
            print(f"[OEA Beirut] Error: Failed to fetch career portal (status {r.status_code})")
            return []
    except Exception as e:
        print(f"[OEA Beirut] Error connecting to career portal: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    careers = soup.find_all(class_="type-career")
    print(f"[OEA Beirut] Found {len(careers)} total job listings on homepage.")
    
    matches_found = []
    
    for idx, card in enumerate(careers):
        try:
            # 1. Parse title and detail URL
            title_h2 = card.find("h2", class_="job-title")
            if not title_h2:
                continue
            title_a = title_h2.find("a")
            if not title_a:
                continue
                
            title = title_a.get_text(strip=True)
            detail_url = title_a.get("href")
            
            # Normalise detail URL
            if detail_url and not detail_url.startswith("http"):
                detail_url = urllib.parse.urljoin(url, detail_url)
                
            if not detail_url or detail_url in existing_urls:
                # Already processed or empty
                continue
                
            # 2. Parse company
            company = ""
            company_el = card.find("h4", class_="company-title")
            if company_el:
                # remove the <span class="addon"> element containing "عبر"
                company_el_copy = BeautifulSoup(str(company_el), "html.parser")
                addon = company_el_copy.find("span", class_="addon")
                if addon:
                    addon.decompose()
                company = company_el_copy.get_text(strip=True)
            else:
                company = "OEA Beirut"

            # 3. Parse initial deadline if present
            deadline = "See listing"
            deadline_el = card.find(class_="deadline-time")
            if deadline_el:
                deadline = deadline_el.get_text(strip=True)
                
            # 4. Check if listing title matches keywords before executing full detail fetch
            # We also check if it's architectural/planning category based on card classes
            card_classes = card.get("class", [])
            is_architectural = any("architect" in str(cls).lower() for cls in card_classes)
            
            if not (matches_profile(title, "", "Lebanon") or is_architectural):
                # If the title is completely irrelevant, skip
                continue
                
            print(f"[OEA Beirut] Processing relevant job: '{title}' by '{company}'")
            
            # Fetch detail page
            try:
                import time
                time.sleep(1.5) # Polite delay
                dr = requests.get(detail_url, headers=headers, impersonate="chrome120", timeout=20)
                if dr.status_code == 200:
                    dsoup = BeautifulSoup(dr.text, "html.parser")
                    
                    # Extract email address
                    email = ""
                    # Check for data-cfemail
                    cf_el = dsoup.find(attrs={"data-cfemail": True})
                    if cf_el:
                        email = decode_cf_email(cf_el["data-cfemail"])
                    else:
                        # Fallback regex search for standard emails in body text
                        body_txt = dsoup.body.get_text() if dsoup.body else ""
                        email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", body_txt)
                        if email_match:
                            email = email_match.group(0)

                    # Extract full description
                    article = dsoup.find("article")
                    if article:
                        desc = article.get_text(separator="\n", strip=True)
                    else:
                        desc = dsoup.body.get_text(separator="\n", strip=True) if dsoup.body else "See listing for details."
                        
                    # Extract location
                    loc = "Lebanon"
                    # Try finding location in meta tags or page text
                    for meta_item in dsoup.find_all(class_=lambda x: x and "location" in str(x).lower()):
                        loc_text = meta_item.get_text(strip=True)
                        if loc_text:
                            loc = loc_text
                            break
                            
                    # Perform profile matching and AI scoring on full details
                    if matches_profile(title, desc, loc):
                        score, reason, reqs = get_ai_evaluation(title, desc, loc, job_url=detail_url)
                        
                        # Add deobfuscated email and contact details directly in description
                        clean_desc = desc
                        if email:
                            clean_desc = f"Contact Email: {email}\n\n" + clean_desc
                            
                        match = {
                            "Platform": f"OEA - {company}" if company else "OEA",
                            "Title": title,
                            "Location": loc,
                            "Description": clean_description(clean_desc),
                            "Deadline": deadline,
                            "URL": detail_url,
                            "Match Score": score,
                            "Match Reason": reason,
                            "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs,
                            "Status": "New"
                        }
                        db.save_job(match)
                        matches_found.append(match)
                        print(f"  => MATCH FOUND: '{title}' (Score: {score})")
            except Exception as de:
                print(f"  Warning: failed to process details for {detail_url}: {de}")
        except Exception as ce:
            print(f"  Warning: failed to parse listing card: {ce}")
            
    print(f"[OEA Beirut] Completed. Discovered {len(matches_found)} matches.")
    return matches_found

def scrape_jobs_for_lebanon(existing_urls=None):
    """
    Scrapes the Jobs for Lebanon portal powered by SmartRecruiters API.
    Bypasses direct HTML scraping by utilizing their clean JSON API.
    """
    import urllib.parse
    import requests
    
    print("\n--- [Jobs for Lebanon] Initiating scraper... ---")
    if existing_urls is None:
        existing_urls = []
        
    matches_found = []
    
    # We query the API for each keyword to keep search results targeted
    for keyword in KEYWORDS:
        print(f"[Jobs for Lebanon] Searching keyword: '{keyword}'...")
        query_url = f"https://api.smartrecruiters.com/v1/companies/JobsForLebanon/postings?q={urllib.parse.quote(keyword)}&limit=100"
        
        try:
            r = requests.get(query_url, timeout=15)
            if r.status_code != 200:
                print(f"  Warning: failed to query keyword {keyword} (status {r.status_code})")
                continue
                
            data = r.json()
            postings = data.get("content", [])
            print(f"  Found {len(postings)} total listings for '{keyword}'.")
            
            for post in postings:
                try:
                    job_id = post.get("id")
                    title = post.get("name", "")
                    detail_url = f"https://jobs.smartrecruiters.com/JobsForLebanon/{job_id}"
                    
                    if not job_id or detail_url in existing_urls or any(m["URL"] == detail_url for m in matches_found):
                        continue
                        
                    # Extract location
                    loc_data = post.get("location", {})
                    loc = loc_data.get("fullLocation") or loc_data.get("city") or "Lebanon"
                    
                    # Fetch details using API to get rich description
                    detail_api_url = f"https://api.smartrecruiters.com/v1/companies/JobsForLebanon/postings/{job_id}"
                    dr = requests.get(detail_api_url, timeout=15)
                    if dr.status_code != 200:
                        continue
                        
                    detail_data = dr.json()
                    
                    # Build full description from jobAd sections
                    job_ad = detail_data.get("jobAd", {})
                    sections = job_ad.get("sections", {})
                    desc_parts = []
                    
                    for sec_key in ["companyDescription", "jobDescription", "qualifications", "additionalInformation"]:
                        sec = sections.get(sec_key, {})
                        sec_title = sec.get("title")
                        sec_text = sec.get("text")
                        if sec_text:
                            if sec_title:
                                desc_parts.append(f"### {sec_title}\n{sec_text}")
                            else:
                                desc_parts.append(sec_text)
                                
                    description = "\n\n".join(desc_parts)
                    
                    # Double-check keyword and location profile match on full details
                    if matches_profile(title, description, loc):
                        # Perform AI scoring/summary
                        score, reason, reqs = get_ai_evaluation(title, description, loc, job_url=detail_url)
                        
                        match = {
                            "Platform": "Jobs for Lebanon",
                            "Title": title,
                            "Location": loc,
                            "Description": clean_description(description),
                            "Deadline": "See listing",
                            "URL": detail_url,
                            "Match Score": score,
                            "Match Reason": reason,
                            "Key Requirements": ", ".join(reqs) if isinstance(reqs, list) else reqs,
                            "Status": "New"
                        }
                        db.save_job(match)
                        matches_found.append(match)
                        print(f"  => MATCH FOUND: '{title}' (Score: {score})")
                except Exception as pe:
                    print(f"  Warning: failed parsing posting: {pe}")
        except Exception as e:
            print(f"  Warning: error querying Jobs for Lebanon for keyword '{keyword}': {e}")
            
    print(f"[Jobs for Lebanon] Completed. Discovered {len(matches_found)} matches.")
    return matches_found

if __name__ == "__main__":
    run_pipeline()
