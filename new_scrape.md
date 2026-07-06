# Implementation Guide: Job Market Evolution Dashboard

This document provides a detailed technical plan to transform the Gesamtkunstwerk application from a simple job finder into a powerful tool for analyzing job market trends over time.

## **Objective**

The goal is to build a historical archive of job postings and create a new "Market Trends" dashboard to visualize this data. This will allow us to track the demand for specific skills, salary trends, and more.

The implementation is broken into three phases:
1.  **Backend & Data Model Changes:** Modify the application to archive data instead of deleting it.
2.  **New Analysis API Endpoint:** Create a backend endpoint to process the historical data.
3.  **Frontend Dashboard:** Build the UI to visualize the trends.

---

## **Phase 1: Backend & Data Model Changes (The Foundation)**

This is the most critical phase. We must modify the application to preserve data for historical analysis.

### **Step 1.1: Modify Database Logic to Archive Old Jobs**

We need to stop deleting old job posts to build our archive. We will alter the `prepare_new_scan` function in `db.py` to archive old, "New" jobs instead of deleting them.

**File:** `db.py`
**Function:** `prepare_new_scan()`

**Current Code:**
```python
def prepare_new_scan():
    # ...
    # Mark old 'New' matches as 'Expired'
    c.execute("UPDATE jobs SET status = 'Expired' WHERE status = 'New'")
    
    # Delete expired jobs older than 30 days
    c.execute("DELETE FROM jobs WHERE status = 'Expired' AND date_added < datetime('now', '-30 days')")
    # ...
```

**Proposed Change:**
We will remove the `DELETE` statement entirely. This ensures every job ever scraped remains in the database for analysis. We can still mark them as `Archived` to hide them from the main feed if desired.

**New Code:**
```python
def prepare_new_scan():
    """
    Archives 'New' jobs older than 7 days to clean up the main feed,
    but preserves them in the database for historical analysis.
    """
    conn = get_db_connection()
    c = conn.cursor()
    # Mark old, untouched jobs as 'Archived' instead of deleting them.
    c.execute("UPDATE jobs SET status = 'Archived' WHERE status = 'New' AND date_added < datetime('now', '-7 days')")
    
    conn.commit()
    conn.close()
```

### **Step 1.2: Enhance Data Capture**

To perform more meaningful analysis, we need to capture more data points, specifically salary and experience level.

**1. Update the AI Prompt:**
Modify the prompt in `scraper.py` to instruct Gemini to extract this new information.

**File:** `scraper.py`
**Function:** `get_ai_evaluation()`

**New Prompt Snippet:**
```python
prompt = f"""
...
Determine:
1. Match Score (0 to 100%)...
2. Match Reason...
3. Key Requirements...
4. Salary Info (string): Extract any mention of salary, currency (LBP, USD), or terms like 'fresh dollars'. If none, return "N/A".
5. Experience Level (string): Categorize the role as 'Entry-level', 'Mid-level', 'Senior', or 'Manager'.

Respond ONLY with a JSON object in this format:
{{
  "match_score": 85,
  "match_reason": "...",
  "key_requirements": ["..."],
  "salary_info": "Up to 2500 USD (Fresh)",
  "experience_level": "Mid-level"
}}
"""
```
You will also need to update the code that parses this JSON response to handle the new fields and save them to the database.

**2. Update the Database Schema:**
Add columns to the `jobs` table to store this new data. This requires an `ALTER TABLE` command.

**File:** `db.py`
**Function:** `init_db()`

**Add these lines to the `CREATE TABLE` statement:**
```python
c.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        ...,
        key_requirements TEXT,
        status TEXT DEFAULT 'New',
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        salary_info TEXT,          -- ADD THIS LINE
        experience_level TEXT      -- ADD THIS LINE
    )
""")
```
> **Note:** `ALTER TABLE` in SQLite is limited. To add these columns to an existing database, you would typically need to run `ALTER TABLE jobs ADD COLUMN salary_info TEXT;` and `ALTER TABLE jobs ADD COLUMN experience_level TEXT;` directly on the database file.

### **Step 1.3: Implement a Robust Scheduler**

For consistent data, the scraper must run on a reliable schedule. We'll use the `APScheduler` library.

**1. Add to Requirements:**
**File:** `requirements.txt`
```
...
fastapi
uvicorn
apscheduler
```

**2. Configure in Server:**
**File:** `server.py`
Add the following code to set up and start the scheduler when the server launches.

```python
# Add near the top with other imports
from apscheduler.schedulers.background import BackgroundScheduler
import scraper # Ensure scraper is imported

# ... after the app = FastAPI() line ...

def scheduled_scan():
    """A wrapper function for the scheduled job."""
    print("--- [Scheduler] Kicking off daily automated scan. ---")
    # We can add logic here to check if the 'scheduler_enabled' setting is true
    # For now, we assume it runs if the server is on.
    try:
        scraper.run_pipeline()
        print("--- [Scheduler] Daily scan finished. ---")
    except Exception as e:
        print(f"--- [Scheduler] Daily scan failed: {e} ---")

# Check if scheduler is enabled in settings before adding the job
settings = scraper.load_settings() # You might need to expose this function or data
if settings.get("scheduler_enabled", False):
    scheduler = BackgroundScheduler(daemon=True)
    # Schedule to run every day at 8:00 AM server time
    scheduler.add_job(scheduled_scan, 'cron', hour=8, minute=0)
    scheduler.start()
    print("--- [Scheduler] Daily scan has been scheduled to run at 8:00 AM. ---")

```

---

## **Phase 2: New Backend Endpoint for Trend Analysis**

Create a new API endpoint that performs time-series analysis on the historical data and returns it to the frontend.

**File:** `server.py`

**New Endpoint Code:**
```python
@app.get("/api/trends")
async def get_market_trends(keywords: str):
    """
    Analyzes historical job data to identify trends for a given set of keywords.
    Keywords should be a comma-separated string.
    """
    try:
        # Modify get_all_jobs_df to accept a flag to include archived/expired jobs
        df = db.get_all_jobs_df(include_archived=True) 
        if df.empty:
            return {"error": "No historical data available."}

        df['DateAdded'] = pd.to_datetime(df['DateAdded'])
        
        # 1. Analyze Keyword Trends
        keyword_trends = {}
        keywords_to_track = [k.strip().lower() for k in keywords.split(',') if k.strip()]
        
        for keyword in keywords_to_track:
            # Count how many job descriptions contained the keyword per month
            df['has_keyword'] = df['Description'].str.contains(keyword, case=False, na=False)
            trend = df[df['has_keyword']].resample('M', on='DateAdded').size()
            
            # Convert to a dictionary of { "YYYY-MM-DD": count }
            keyword_trends[keyword] = {timestamp.strftime('%Y-%m-%d'): count for timestamp, count in trend.items()}

        return {
            "keyword_trends": keyword_trends,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
> **Note:** This requires modifying `db.get_all_jobs_df()` to accept an `include_archived=True` argument that changes the SQL query to remove the `WHERE status NOT IN ('Expired')` clause.

---

## **Phase 3: Frontend "Market Trends" Dashboard**

Finally, build the UI to display these insights.

### **Step 3.1: Add New Tab and Panel**

**File:** `static/index.html`

1.  **Add the button** to the header navigation:
    ```html
    <nav class="tab-navigation">
        <button class="nav-btn active" id="tab-global-btn">Global Feed</button>
        <button class="nav-btn" id="tab-custom-btn">Custom Directory</button>
        <button class="nav-btn" id="tab-analytics-btn">Analytics</button>
        <button class="nav-btn" id="tab-trends-btn">Market Trends</button> <!-- ADD THIS -->
        <button class="nav-btn" id="tab-settings-btn">Settings</button>
    </nav>
    ```
2.  **Add the panel** for the new dashboard content:
    ```html
    <!-- After the </section> for panel-analytics -->
    <section class="tab-panel" id="panel-trends">
        <div class="actions-bar">
            <div class="search-box" style="max-width: 100%;">
                <input type="text" id="trends-keywords-input" placeholder="Enter skills to track, separated by commas (e.g. Python, Revit, GIS)...">
            </div>
            <div class="action-buttons">
                <button class="btn btn-primary" id="generate-trends-report-btn">Generate Report</button>
            </div>
        </div>
        <div class="chart-grid-full">
            <div class="chart-container" style="height: 400px;">
                <h3>Skill Demand Over Time</h3>
                <canvas id="skill-trend-chart"></canvas>
            </div>
        </div>
    </section>
    ```

### **Step 3.2: Implement Frontend Logic**

**File:** `static/app.js`

1.  **Wire up the new tab** in `initTabs()` just like the others.
2.  **Add event listener** in `initEventListeners()`:
    ```javascript
    document.getElementById('generate-trends-report-btn').addEventListener('click', renderTrendsDashboard);
    ```
3.  **Create the new rendering function:**
    ```javascript
    async function renderTrendsDashboard() {
        const keywords = document.getElementById('trends-keywords-input').value;
        if (!keywords) {
            showToast('Please enter at least one skill or keyword to track.', 'error');
            return;
        }

        showToast('Generating trend report...');
        
        try {
            const response = await fetch(`/api/trends?keywords=${encodeURIComponent(keywords)}`);
            if (!response.ok) throw new Error('Failed to fetch trend data.');

            const trendData = await response.json();
            const keyword_trends = trendData.keyword_trends;

            // Find all unique month labels across all keywords
            const all_labels = new Set();
            Object.values(keyword_trends).forEach(trend => {
                Object.keys(trend).forEach(date => all_labels.add(date));
            });
            const sorted_labels = Array.from(all_labels).sort();

            // Prepare datasets for Chart.js
            const datasets = Object.keys(keyword_trends).map(keyword => {
                const trend = keyword_trends[keyword];
                return {
                    label: keyword,
                    data: sorted_labels.map(label => trend[label] || 0), // Use 0 if no data for that month
                    fill: false,
                    tension: 0.1
                };
            });

            // Render the chart
            new Chart(document.getElementById('skill-trend-chart'), {
                type: 'line',
                data: {
                    labels: sorted_labels.map(l => l.substring(0, 7)), // Format to YYYY-MM
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });

        } catch (e) {
            showToast(e.message, 'error');
        }
    }
    ```
