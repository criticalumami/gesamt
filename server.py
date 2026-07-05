import os
import sys
import json
import csv
import subprocess
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional

# Make sure server can import from current directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import scraper

# Initialize database
db.init_db()

app = FastAPI(title="Gesamtkunstwerk API Server", version="1.0")

# Serve UI static files
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Global background process tracking
active_process = None
LOG_FILE = "pipeline.log"

# Pydantic models
class SettingsPayload(BaseModel):
    keywords: List[str]
    locations: List[str]
    platforms: List[str]
    ai_enabled: bool
    scheduler_enabled: bool
    gemini_api_key: Optional[str] = ""
    gemini_model: Optional[str] = "gemini-flash-latest"
    profile_summary: Optional[str] = ""
    keyword_mode: Optional[str] = "OR"

class OfficeUpdatePayload(BaseModel):
    name: str
    status: Optional[str] = None
    notes: Optional[str] = None

class OfficeScanPayload(BaseModel):
    name: str
    website: str

# Helper to read custom offices from CSV
def read_custom_csv():
    csv_path = "custom.csv"
    if not os.path.exists(csv_path):
        return []
    offices = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Strip keys and values
                clean_row = {k.strip(): v.strip() for k, v in row.items() if k}
                name = clean_row.get("Office Name")
                if not name:
                    continue
                offices.append({
                    "Name": name,
                    "Address": clean_row.get("Address", ""),
                    "Website": clean_row.get("Website", ""),
                    "Email": clean_row.get("E-mail", ""),
                    "Phone": clean_row.get("Phone", ""),
                    "Social": clean_row.get("Social", ""),
                    "Focus": clean_row.get("Note", ""),
                    "Description": clean_row.get("Note", "")
                })
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return offices

# --- API Endpoints ---

@app.get("/")
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Gesamtkunstwerk Front-end not found. Create index.html inside /static</h1>")

@app.get("/api/analytics")
async def get_analytics_data():
    try:
        df = db.get_all_jobs_df()
        if df.empty:
            return {
                "kpis": {"total_matches": 0, "applied_count": 0, "interview_count": 0, "offer_count": 0},
                "funnel": {"stages": [], "counts": []},
                "platforms": {"labels": [], "values": []},
                "timeline": {"dates": [], "counts": []}
            }

        # KPIs
        total_matches = len(df)
        applied_count = len(df[df["Status"] == "Applied"])
        interview_count = len(df[df["Status"] == "Interviewing"])
        offer_count = len(df[df["Status"] == "Offer"])
        kpis = {
            "total_matches": total_matches,
            "applied_count": applied_count,
            "interview_count": interview_count,
            "offer_count": offer_count
        }

        # Funnel Data
        funnel_stages = ["New", "Applied", "Interviewing", "Offer"]
        funnel_counts = [len(df[df["Status"] == stage]) for stage in funnel_stages]
        funnel_counts[0] += sum(funnel_counts[1:])
        funnel_counts[1] += sum(funnel_counts[2:])
        funnel_counts[2] += sum(funnel_counts[3:])
        funnel_data = {"stages": funnel_stages, "counts": funnel_counts}

        # Platform Data
        platform_counts = df["Platform"].value_counts()
        platform_data = {"labels": platform_counts.index.tolist(), "values": platform_counts.values.tolist()}

        # Timeline Data
        df_applied = df[df["Status"] == "Applied"].copy()
        if not df_applied.empty:
            df_applied["DateAdded"] = pd.to_datetime(df_applied["DateAdded"])
            apps_by_day = df_applied.resample('D', on='DateAdded').size()
            timeline_data = {"dates": apps_by_day.index.strftime('%Y-%m-%d').tolist(), "counts": apps_by_day.values.tolist()}
        else:
            timeline_data = {"dates": [], "counts": []}
            
        return {"kpis": kpis, "funnel": funnel_data, "platforms": platform_data, "timeline": timeline_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics")
async def get_analytics_data():
    try:
        df = db.get_all_jobs_df()
        if df.empty:
            return {
                "kpis": {"total_matches": 0, "applied_count": 0, "interview_count": 0, "offer_count": 0},
                "funnel": {"stages": [], "counts": []},
                "platforms": {"labels": [], "values": []},
                "timeline": {"dates": [], "counts": []}
            }

        # KPIs
        total_matches = len(df)
        applied_count = len(df[df["Status"] == "Applied"])
        interview_count = len(df[df["Status"] == "Interviewing"])
        offer_count = len(df[df["Status"] == "Offer"])
        kpis = {
            "total_matches": total_matches,
            "applied_count": applied_count,
            "interview_count": interview_count,
            "offer_count": offer_count
        }

        # Funnel Data
        funnel_stages = ["New", "Applied", "Interviewing", "Offer"]
        funnel_counts = [len(df[df["Status"] == stage]) for stage in funnel_stages]
        funnel_counts[0] += sum(funnel_counts[1:])
        funnel_counts[1] += sum(funnel_counts[2:])
        funnel_counts[2] += sum(funnel_counts[3:])
        funnel_data = {"stages": funnel_stages, "counts": funnel_counts}

        # Platform Data
        platform_counts = df["Platform"].value_counts()
        platform_data = {"labels": platform_counts.index.tolist(), "values": platform_counts.values.tolist()}

        # Timeline Data
        df_applied = df[df["Status"] == "Applied"].copy()
        if not df_applied.empty:
            df_applied["DateAdded"] = pd.to_datetime(df_applied["DateAdded"])
            apps_by_day = df_applied.resample('D', on='DateAdded').size()
            timeline_data = {"dates": apps_by_day.index.strftime('%Y-%m-%d').tolist(), "counts": apps_by_day.values.tolist()}
        else:
            timeline_data = {"dates": [], "counts": []}
            
        return {"kpis": kpis, "funnel": funnel_data, "platforms": platform_data, "timeline": timeline_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs")
async def get_jobs():
    try:
        # Get dataframe from database and convert to dict list
        df = db.get_all_jobs_df()
        if df.empty:
            return []
        
        # Clean null values and convert
        df = df.fillna("")
        jobs_list = df.to_dict(orient="records")
        return jobs_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class JobStatusUpdatePayload(BaseModel):
    url: str
    status: str

@app.post("/api/jobs/update_status")
async def update_job_status_api(payload: JobStatusUpdatePayload):
    try:
        db.update_job_status(payload.url, payload.status)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/jobs")
async def clear_jobs():
    try:
        db.clear_all_jobs()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/offices")
async def get_offices():
    try:
        offices = read_custom_csv()
        if not offices:
            return []
            
        # Merge outreach statuses and notes from DB
        app_status_dict = db.get_office_applications()
        for office in offices:
            name = office["Name"]
            saved = app_status_dict.get(name, {"status": "Uncontacted", "notes": ""})
            office["Status"] = saved.get("status", "Uncontacted")
            office["Notes"] = saved.get("notes", "")
            
        return offices
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/offices/update")
async def update_office(payload: OfficeUpdatePayload):
    try:
        name = payload.name
        app_status_dict = db.get_office_applications()
        saved = app_status_dict.get(name, {"status": "Uncontacted", "notes": ""})
        
        status = payload.status if payload.status is not None else saved.get("status", "Uncontacted")
        notes = payload.notes if payload.notes is not None else saved.get("notes", "")
        
        db.save_office_application(name, status, notes)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/settings")
async def get_settings():
    DEFAULT_KEYWORDS = ["urban planning", "heritage conservation", "architecture", "urban research", "qgis"]
    DEFAULT_LOCATIONS = ["beirut", "paris", "berlin", "hamburg"]
    DEFAULT_PLATFORMS = ["Daleel Madani", "UN Careers", "ReliefWeb", "LinkedIn", "Bayt.com", "EURAXESS", "OEA", "Jobs for Lebanon"]
    
    settings_file = "settings.json"
    data = {
        "keywords": DEFAULT_KEYWORDS,
        "locations": DEFAULT_LOCATIONS,
        "platforms": DEFAULT_PLATFORMS,
        "ai_enabled": True,
        "scheduler_enabled": False,
        "gemini_api_key": "",
        "gemini_model": "gemini-flash-latest",
        "profile_summary": "",
        "keyword_mode": "OR"
    }
    
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                saved = json.load(f)
                data.update(saved)
        except Exception:
            pass
    return data

@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    settings_file = "settings.json"
    try:
        data = payload.dict()
        with open(settings_file, "w") as f:
            json.dump(data, f, indent=2)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/scan")
async def run_scan(override_keywords: Optional[str] = None):
    global active_process
    
    # Check if process is already running
    if active_process is not None and active_process.poll() is None:
        return {"status": "already running"}
        
    # Clear old log file
    if os.path.exists(LOG_FILE):
        try:
            os.remove(LOG_FILE)
        except Exception:
            pass
            
    # Resolve python interpreter
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")
    python_bin = venv_python if os.path.exists(venv_python) else sys.executable
    
    try:
        # Build command with temporary keyword override if provided
        cmd = [python_bin, "-u", "scraper.py"]
        if override_keywords:
            cmd.extend(["--override-keywords", override_keywords])
            
        # Start scraper pipeline as process, redirect output to pipeline.log
        log_f = open(LOG_FILE, "w")
        active_process = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            text=True
        )
        return {"status": "started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {e}")

@app.post("/api/scan/stop")
async def stop_scan():
    global active_process
    if active_process is not None and active_process.poll() is None:
        try:
            active_process.terminate()
            # Wait up to 3 seconds for it to exit, then kill if needed
            try:
                active_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                active_process.kill()
            
            # Append stop message to log
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write("\n[Pipeline] Scan stopped by user.\n")
            return {"success": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to stop pipeline: {e}")
    return {"success": False, "detail": "No active scan running"}

@app.get("/api/logs")
async def get_logs():
    global active_process
    
    status = "idle"
    if active_process is not None and active_process.poll() is None:
        status = "running"
        
    logs_content = ""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs_content = f.read()
        except Exception as e:
            logs_content = f"Error reading log file: {e}"
            
    return {"status": status, "logs": logs_content}

@app.post("/api/scan/office")
async def scan_office(payload: OfficeScanPayload):
    try:
        # Run custom office website scan using scraper library
        result = scraper.scrape_custom_office_website(payload.name, payload.website)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/keywords/expand")
async def expand_keywords():
    settings_file = "settings.json"
    if not os.path.exists(settings_file):
        raise HTTPException(status_code=400, detail="Please save your settings first.")
        
    try:
        with open(settings_file, "r") as f:
            settings = json.load(f)
            
        api_key = settings.get("gemini_api_key", "")
        profile = settings.get("profile_summary", "")
        keywords = settings.get("keywords", [])
        
        if not api_key:
            raise HTTPException(status_code=400, detail="Gemini API Key is not configured.")
            
        success, result = scraper.expand_keywords_with_ai(profile, keywords, api_key)
        if success:
            return {"success": True, "keywords": result}
        else:
            return {"success": False, "error": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def extract_text_from_pdf(file_bytes):
    import io
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return ""

def analyze_resume_text(resume_text, api_key, model="gemini-1.5-flash"):
    if not api_key:
        return None, "No API key configured."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    prompt = f"""Analyze the following candidate resume text.
Extract:
1. Target Keywords: A list of 4-6 most important skills, tools, or domain keywords (e.g. "urban planning", "QGIS", "architecture").
2. Candidate Profile Summary: A concise, 2-3 sentence professional summary of the candidate's core expertise, experience level, and career focus.

Resume Text:
{resume_text}

Respond ONLY with a JSON object in this format (no markdown code blocks, no backticks, just raw JSON):
{{
  "keywords": ["keyword1", "keyword2"],
  "profile_summary": "Summary..."
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
        import requests
        import re
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if r.status_code != 200:
            return None, f"API HTTP Error {r.status_code}: {r.text}"
            
        res_json = r.json()
        if 'candidates' not in res_json or not res_json['candidates']:
            return None, f"Invalid response structure: {r.text}"
            
        text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)
            
        try:
            parsed = json.loads(text)
            return parsed, None
        except Exception as je:
            return None, f"JSON parse error: {je}. Raw output was: {text}"
            
    except Exception as e:
        return None, f"Connection/Network error: {e}"

@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    # Read file bytes
    file_bytes = await file.read()
    
    # Extract text
    text = extract_text_from_pdf(file_bytes)
    if not text:
        raise HTTPException(status_code=400, detail="Could not extract text from this PDF file.")
        
    # Load settings to get Gemini API key
    settings_file = "settings.json"
    api_key = ""
    model = "gemini-flash-latest"
    
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                saved = json.load(f)
                api_key = saved.get("gemini_api_key", "")
                model = saved.get("gemini_model", "gemini-flash-latest")
        except Exception:
            pass
            
    if not api_key:
        raise HTTPException(status_code=400, detail="Please enter and save a Gemini API Key in the settings first.")
        
    # Call Gemini to parse resume text
    parsed, err = analyze_resume_text(text, api_key, model)
    if err:
        raise HTTPException(status_code=500, detail=f"AI parsing error: {err}")
        
    return {
        "success": True,
        "keywords": parsed.get("keywords", []),
        "profile_summary": parsed.get("profile_summary", "")
    }

# Mount static folder
app.mount("/", StaticFiles(directory=static_dir), name="static")
