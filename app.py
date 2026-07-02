import os
import sys
import time
import subprocess
import json
import threading
from datetime import datetime
import pandas as pd
import streamlit as st

import importlib
import db
importlib.reload(db)
db.init_db()

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

def make_expandable_text(text_str, max_len=60):
    if len(text_str) <= max_len:
        return text_str
    
    preview = text_str[:max_len].strip()
    return (
        f"<details class='expandable-details'>"
        f"<summary>"
        f"<span class='preview-text'>{preview}...</span> "
        f"<span class='action-link'></span>"
        f"</summary>"
        f"<div class='full-text'>{text_str}</div>"
        f"</details>"
    )

def update_job_status(url, new_status):
    try:
        db.update_job_status(url, new_status)
        st.toast(f"Moved to {new_status}!")
        time.sleep(0.5)
        st.rerun()
    except Exception as e:
        st.error(f"Error updating status: {e}")

def delete_job_by_url(url):
    try:
        db.delete_job(url)
        st.toast("Match deleted!")
        time.sleep(0.5)
        st.rerun()
    except Exception as e:
        st.error(f"Error deleting job: {e}")

# --- UI Config Constants (Easy Reversion) ---
USE_GRAYSCALE = True
USE_EMOJIS = False

# Page Configuration
page_title_str = "Gesamtkunstwerk \u262d"
st.set_page_config(
    page_title=page_title_str,
    page_icon="favicon.png",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Theme colors mapping
accent_light = "#000000" if USE_GRAYSCALE else "#e60000"
accent_dark = "#ffffff" if USE_GRAYSCALE else "#ff3333"

# Minimalist Swiss Style CSS Theme variables (Josef Müller-Brockmann inspired typographic grid)
css = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

:root {
    --bg: #ffffff;
    --text: #000000;
    --text-muted: #555555;
    --border: #000000;
    --border-subtle: #e0e0e0;
    --accent: __ACCENT_LIGHT__;
}

@media (prefers-color-scheme: dark) {
    :root {
        --bg: #000000;
        --text: #ffffff;
        --text-muted: #888888;
        --border: #ffffff;
        --border-subtle: #222222;
        --accent: __ACCENT_DARK__;
    }
}

/* Force all corners globally straight */
* {
    border-radius: 0px !important;
}

/* EXCEPT the circular loading spinner */
div[data-testid="stSpinner"] *,
[class*="stSpinner"] *,
.stSpinner *,
[class*="spinner"] *,
[class*="Spinner"] * {
    border-radius: 50% !important;
}

/* Hide Streamlit default styling elements */
header[data-testid="stHeader"], footer, [data-testid="stToolbar"],
[data-testid="stDecoration"], .stDeployButton,
div[data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}

html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], .main, .block-container, section[data-testid="stMain"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: "Inter", "Helvetica Neue", Helvetica, Arial, sans-serif !important;
}

.block-container {
    max-width: 900px !important;
    padding-top: 3rem !important;
}

/* Minimal Title Header Row */
.header-row {
    border-bottom: 2px solid var(--border);
    padding-bottom: 0.5rem;
    margin-bottom: 2rem;
}
.app-title {
    font-size: 1.75rem;
    font-weight: 900;
    letter-spacing: -0.04em;
    text-transform: uppercase;
    color: var(--text);
}

/* Flatten Streamlit Buttons */
button[kind="secondary"], button[kind="primary"], div[data-testid="stButton"] button {
    border-radius: 0px !important;
    border: 1px solid var(--border) !important;
    background-color: var(--bg) !important;
    color: var(--text) !important;
    text-transform: uppercase !important;
    font-weight: 700 !important;
    letter-spacing: 0.05em !important;
    font-size: 0.75rem !important;
    height: 40px !important;
    min-height: 40px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: all 0.15s ease !important;
}
button[kind="secondary"]:hover, button[kind="primary"]:hover, div[data-testid="stButton"] button:hover {
    background-color: var(--text) !important;
    color: var(--bg) !important;
}

/* Flatten Input fields wrappers */
div[data-baseweb="input"], div[data-baseweb="select"], textarea {
    border-radius: 0px !important;
    border: 1px solid var(--border) !important;
    background-color: var(--bg) !important;
    color: var(--text) !important;
}

/* Force all inner nested container divs to inherit parent's background color */
div[data-baseweb="input"] div, 
div[data-baseweb="select"] div {
    background-color: transparent !important;
}

/* Strip borders from raw inputs, selectors, and inner elements to prevent double border nesting */
input, 
select,
div[data-baseweb="input"] input, 
div[data-baseweb="select"] input,
div[data-baseweb="input"] button {
    border: none !important;
    background-color: transparent !important;
    box-shadow: none !important;
    border-radius: 0px !important;
}

/* Set explicit height for single-line input wrappers and inner input tags */
div[data-baseweb="input"], div[data-baseweb="input"] input {
    height: 40px !important;
    min-height: 40px !important;
}

/* Minimal Expander - Strict sharp borders */
.stExpander, 
div[data-testid="stExpander"], 
div[data-testid="stExpander"] > details, 
div[data-testid="stExpander"] summary {
    border-radius: 0px !important;
}
.stExpander {
    border: 1px solid var(--border) !important;
    background-color: transparent !important;
    margin-bottom: 1.5rem !important;
}
div[data-testid="stExpanderDetails"] {
    padding: 1.25rem !important;
    border-top: 1px solid var(--border) !important;
}

/* details.expandable-details */
details.expandable-details {
    display: block;
    width: 100%;
}
details.expandable-details summary {
    cursor: pointer;
    outline: none;
    list-style: none;
    display: inline-block;
    width: 100%;
}
details.expandable-details summary::-webkit-details-marker {
    display: none !important;
}
details.expandable-details .action-link {
    color: var(--accent);
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 6px;
    display: inline-block;
}
details.expandable-details .action-link::after {
    content: "↓ Show Description";
}
details.expandable-details[open] .action-link::after {
    content: "↑ Hide Description";
}
details.expandable-details[open] .preview-text {
    display: none !important;
}
details.expandable-details .full-text {
    margin-top: 8px;
    font-size: 0.85rem;
    line-height: 1.5;
    color: var(--text);
    white-space: pre-wrap;
}

/* Card Feed Layout - Swiss Style */
.job-card {
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border-subtle);
    padding: 1.5rem 0;
    margin-bottom: 0px;
    background-color: transparent;
}
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1.5rem;
    margin-bottom: 0.75rem;
}
.card-title {
    font-size: 1.3rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--text);
    margin: 0;
    line-height: 1.2;
}
.card-title a {
    color: var(--text);
    text-decoration: none;
}
.card-title a:hover {
    color: var(--accent);
}
.card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-bottom: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
}
.badge {
    display: inline-block;
    padding: 0.2rem 0.4rem;
    border-radius: 0px;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    line-height: 1;
}
.badge-score {
    background-color: var(--accent);
    color: var(--bg) !important;
    border: none;
}
.badge-score-high {
    background-color: var(--accent);
    color: var(--bg) !important;
    border: none;
}
.badge-source {
    background-color: var(--text);
    color: var(--bg);
    border: none;
}

/* Score threshold slider */
div[data-testid="stSlider"] > div {
    padding-top: 0.25rem !important;
}
div[data-testid="stSlider"] label {
    font-size: 0.75rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    color: var(--text-muted) !important;
}
div[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
    border-radius: 0px !important;
    background-color: var(--accent) !important;
    border: none !important;
    width: 14px !important;
    height: 14px !important;
}
div[data-testid="stSlider"] [data-baseweb="slider"] div[class*="Track"] div {
    border-radius: 0px !important;
    background-color: var(--accent) !important;
}

/* Flatten Streamlit Tabs */
div[data-testid="stTabBar"] {
    border-bottom: 2px solid var(--border) !important;
}
div[data-testid="stTabBar"] button {
    border-radius: 0px !important;
    border: none !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    font-size: 0.8rem !important;
    padding: 0.5rem 1rem !important;
    color: var(--text-muted) !important;
}
div[data-testid="stTabBar"] button[aria-selected="true"] {
    color: var(--text) !important;
    border-bottom: 3px solid var(--accent) !important;
}

/* Fix for multiselect input position & remove border from its hidden search input */
div[data-baseweb="value-container"] {
    display: flex;
    flex-wrap: wrap;
}
div[data-baseweb="value-container"] [data-baseweb="multi-value"] {
    order: 1;
}
div[data-baseweb="value-container"] input {
    order: 2;
    border: none !important;
    background-color: transparent !important;
    box-shadow: none !important;
    height: auto !important;
    min-height: 0 !important;
    padding: 0 !important;
    width: auto !important;
}
div[data-baseweb="select"] input {
    border: none !important;
    background-color: transparent !important;
    box-shadow: none !important;
    height: auto !important;
    min-height: 0 !important;
    padding: 0 !important;
    width: auto !important;
}

/* Align columns at the bottom to align buttons with adjacent text inputs */
div[data-testid="stHorizontalBlock"] {
    align-items: flex-end !important;
}
</style>
"""

# Apply placeholder color values
css = css.replace("__ACCENT_LIGHT__", accent_light).replace("__ACCENT_DARK__", accent_dark)

# Append specific grayscale styling overrides to keep input indicators and checkboxes black/white
if USE_GRAYSCALE:
    css_grays = """
<style>
/* Grayscale overrides for selected multiselect tags */
[data-baseweb="tag"] {
    background-color: var(--text) !important;
    color: var(--bg) !important;
    border-radius: 0px !important;
    border: 1px solid var(--text) !important;
}
[data-baseweb="tag"] * {
    color: var(--bg) !important;
    fill: var(--bg) !important;
}
[data-baseweb="tag"] button {
    background-color: transparent !important;
}
[data-baseweb="tag"] button:hover {
    background-color: rgba(255,255,255,0.2) !important;
}

/* Grayscale styling for checked checkboxes */
div[data-testid="stCheckbox"] label div[role="checkbox"][aria-checked="true"] {
    background-color: var(--text) !important;
    border-color: var(--text) !important;
}
div[data-testid="stCheckbox"] label div[role="checkbox"] {
    border-radius: 0px !important;
}

/* Grayscale styling for checked toggle switches */
div[data-testid="stWidgetLabel"] + div button[role="switch"][aria-checked="true"] {
    background-color: var(--text) !important;
}

/* Grayscale styling for checked radio buttons */
div[data-testid="stRadio"] [role="radiogroup"] [role="radio"] div {
    border-color: var(--text) !important;
}
div[data-testid="stRadio"] [role="radiogroup"] [role="radio"][aria-checked="true"] div {
    border-color: var(--text) !important;
    background-color: var(--text) !important;
}
div[data-testid="stRadio"] [role="radiogroup"] [role="radio"][aria-checked="true"] div div {
    background-color: var(--bg) !important;
}

/* Grayscale styling for st.info and other notification blocks */
div[data-testid="stNotification"] {
    background-color: var(--border-subtle) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 0px !important;
}
div[data-testid="stNotification"] * {
    color: var(--text) !important;
}

/* Tighten the vertical spacing of the settings expander panel */
div[data-testid="stExpanderDetails"] [data-testid="stVerticalBlock"] {
    gap: 0.5rem !important;
}
div[data-testid="stExpanderDetails"] hr {
    margin-top: 0.5rem !important;
    margin-bottom: 0.5rem !important;
}
</style>
"""
    css = css.replace("</style>", "") + css_grays.replace("<style>", "")

st.markdown(css, unsafe_allow_html=True)

# Header Row
header_title = "Gesamtkunstwerk \u262d"
st.markdown(f'<div class="header-row"><div class="app-title">{header_title}</div></div>', unsafe_allow_html=True)



def render_custom_tab():
    import db
    import pandas as pd
    import os
    import time
    
    st.subheader("Custom Offices Directory")
    
    # Check if custom.csv exists
    csv_path = "custom.csv"
    if not os.path.exists(csv_path):
        st.info("custom.csv was not found in the root directory.")
        return
        
    try:
        # Load and clean columns
        df = pd.read_csv(csv_path)
        df.columns = [c.strip() for c in df.columns]
        # Clean null values
        df = df.fillna("")
    except Exception as e:
        st.error(f"Failed to load custom.csv: {e}")
        return
        
    if df.empty:
        st.info("No offices found in custom.csv.")
        return

    # Extract unique locations/neighborhoods for filtering
    def extract_neighborhood(addr):
        if not addr:
            return "Unknown"
        parts = [p.strip() for p in addr.split(",")]
        return parts[0] if parts else "Unknown"

    df["Neighborhood"] = df["Address"].apply(extract_neighborhood)
    neighborhoods = sorted(list(df["Neighborhood"].unique()))
    if "Unknown" in neighborhoods:
        neighborhoods.remove("Unknown")
        neighborhoods.append("Unknown")

    # Filter section
    col_search, col_filter = st.columns([2, 1])
    with col_search:
        search_query = st.text_input("Search Offices", "", placeholder="Search by office name, notes, or address...", label_visibility="collapsed")
    with col_filter:
        selected_neighborhoods = st.multiselect("Filter by Neighborhood", options=neighborhoods, placeholder="Filter by neighborhood...")

    # Filter the dataframe
    filtered_df = df.copy()
    if search_query:
        query = search_query.lower()
        filtered_df = filtered_df[
            filtered_df["Office Name"].str.lower().str.contains(query) |
            filtered_df["Address"].str.lower().str.contains(query) |
            filtered_df["Note"].str.lower().str.contains(query)
        ]
    if selected_neighborhoods:
        filtered_df = filtered_df[filtered_df["Neighborhood"].isin(selected_neighborhoods)]

    # Fetch stored applications and notes status from DB
    try:
        app_status_dict = db.get_office_applications()
    except Exception as e:
        st.error(f"Failed to fetch statuses from DB: {e}")
        app_status_dict = {}

    st.markdown(f"<div style='color: var(--text-muted); font-size: 0.85rem; margin-bottom: 1.5rem;'>Showing {len(filtered_df)} of {len(df)} target studios.</div>", unsafe_allow_html=True)

    # Status options for spontaneous outreach
    status_options = ["Uncontacted", "Portfolio Sent", "In Conversation", "Interview Scheduled", "No Openings"]

    # Render each office card
    for idx, row in filtered_df.reset_index().iterrows():
        office_name = row["Office Name"]
        if not office_name:
            continue
            
        address = row.get("Address", "")
        website = row.get("Website", "")
        email = row.get("E-mail", "")
        phone = row.get("Phone", "")
        social = row.get("Social", "")
        note = row.get("Note", "")

        # Get saved outreach status and notes from database, defaulting to empty
        saved_data = app_status_dict.get(office_name, {"status": "Uncontacted", "notes": ""})
        current_status = saved_data["status"]
        current_notes = saved_data["notes"]

        # Make sure current_status is valid, otherwise fallback
        if current_status not in status_options:
            current_status = "Uncontacted"

        card_html = f"""<div class="job-card" style="margin-bottom: 1rem; border: 1px solid var(--border-subtle); padding: 1rem; background-color: transparent;">
<div class="card-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
<h4 class="card-title" style="margin:0; font-size: 1.1rem; font-weight: 700;">{office_name}</h4>
<div>
<span class="badge badge-source" style="background-color: var(--border-subtle); color: var(--text); padding: 0.2rem 0.4rem; font-size: 0.75rem;">{address}</span>
</div>
</div>
<div class="card-meta" style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.5rem; display: flex; gap: 1rem; flex-wrap: wrap;">"""
        
        meta_items = []
        if website:
            meta_items.append(f'<a href="{website if website.startswith("http") else "https://" + website}" target="_blank" class="job-link" style="color: var(--text); font-weight: 600; text-decoration: underline;">Website</a>')
        if email:
            meta_items.append(f'Email: <a href="mailto:{email}" class="job-link" style="color: var(--text); text-decoration: underline;">{email}</a>')
        if phone:
            meta_items.append(f'Phone: {phone}')
        if social:
            meta_items.append(f'<a href="{social}" target="_blank" class="job-link" style="color: var(--text); text-decoration: underline;">Socials</a>')
            
        card_html += " | ".join(meta_items)
        card_html += f"""</div>"""
        
        if note:
            card_html += f"""<div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 0.5rem; line-height: 1.4; border-top: 1px dashed var(--border-subtle); padding-top: 0.5rem;">
<strong>Note:</strong> {note}
</div>"""
        card_html += "</div>"
        
        st.markdown(card_html, unsafe_allow_html=True)

        # Build form/inputs row for notes and status tracking
        col_status, col_notes, col_action = st.columns([1.5, 3.0, 1.2])
        
        with col_status:
            new_status = st.selectbox(
                "Outreach Status",
                options=status_options,
                index=status_options.index(current_status),
                key=f"status_{idx}_{office_name}",
                label_visibility="collapsed"
            )
            
        with col_notes:
            new_notes = st.text_input(
                "Notes",
                value=current_notes,
                key=f"notes_{idx}_{office_name}",
                placeholder="Spoke with Katia, send portfolio in August...",
                label_visibility="collapsed"
            )
            
        with col_action:
            col_save, col_scan = st.columns(2)
            with col_save:
                if st.button("Save", key=f"save_{idx}_{office_name}", use_container_width=True, help="Save status and notes to database"):
                    db.save_office_application(office_name, new_status, new_notes)
                    st.toast(f"Saved changes for {office_name}!")
            with col_scan:
                if website:
                    if st.button("Scan", key=f"scan_{idx}_{office_name}", use_container_width=True, help="Scan website with Gemini AI for active roles"):
                        with st.spinner("Scanning..."):
                            import scraper
                            res = scraper.scrape_custom_office_website(office_name, website)
                            if res.get("success"):
                                roles = res.get("roles", [])
                                if roles:
                                    st.success(f"Discovered {len(roles)} active roles! Saved to main feed.")
                                    time.sleep(1.5)
                                    st.rerun()
                                else:
                                    st.info("No active openings matching your profile found on their site.")
                            else:
                                st.error(f"Scan failed: {res.get('error')}")
                else:
                    st.markdown("<div style='text-align: center; color: var(--text-muted); font-size: 0.8rem; height: 100%; display: flex; align-items: center; justify-content: center;'>-</div>", unsafe_allow_html=True)
                    
        st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)


tab_global, tab_custom = st.tabs(["Global", "Custom"])

with tab_global:
    # Expandable Settings Section
    with st.expander("Filter Configuration", expanded=False):
        # Load settings from settings.json
        DEFAULT_KEYWORDS = ["urban planning", "heritage conservation", "architecture", "urban research", "qgis"]
        DEFAULT_LOCATIONS = ["beirut", "paris", "berlin", "hamburg"]
        DEFAULT_PLATFORMS = ["Daleel Madani", "UN Careers", "ReliefWeb", "LinkedIn", "Bayt.com", "EURAXESS"]

        settings = {"keywords": DEFAULT_KEYWORDS, "locations": DEFAULT_LOCATIONS, "platforms": DEFAULT_PLATFORMS}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r") as f:
                    settings = json.load(f)
            except Exception:
                pass

        kw_str = ", ".join(settings.get("keywords", DEFAULT_KEYWORDS))
        loc_str = ", ".join(settings.get("locations", DEFAULT_LOCATIONS))
        selected_platforms = settings.get("platforms", DEFAULT_PLATFORMS)

        # Keyword input with Auto-Expand column layout
        expand_msg = None
        expand_msg_type = None  # "error" or "success"

        col_kw_1, col_kw_2 = st.columns([5, 1.5])
        with col_kw_1:
            new_kw = st.text_input("Target Keywords (comma separated)", kw_str)
        with col_kw_2:
            btn_label = "Auto-Expand" if not USE_EMOJIS else "✨ Auto-Expand"
            if st.button(btn_label, help="Use Gemini to suggest highly relevant keywords for your profile"):
                gemini_key_for_expand = settings.get("gemini_api_key", "")
                if not gemini_key_for_expand:
                    expand_msg = "Please enter and save a Gemini API Key first."
                    expand_msg_type = "error"
                else:
                    with st.spinner("Expanding..."):
                        import importlib
                        import scraper
                        importlib.reload(scraper)
                        current_list = [k.strip() for k in new_kw.split(",") if k.strip()]
                        success, result = scraper.expand_keywords_with_ai(
                            settings.get("profile_summary", ""),
                            current_list,
                            gemini_key_for_expand
                        )
                        if success:
                            settings["keywords"] = result
                            try:
                                with open("settings.json", "w") as f:
                                    json.dump(settings, f, indent=2)
                                expand_msg = "Keywords expanded!"
                                expand_msg_type = "success"
                            except Exception as ex:
                                expand_msg = f"Failed to save settings: {ex}"
                                expand_msg_type = "error"
                        else:
                            expand_msg = f"AI Keyword Expansion Failed: {result}"
                            expand_msg_type = "error"

        # Render error/success messages full-width below the columns to prevent layout distortion
        if expand_msg:
            if expand_msg_type == "success":
                st.success(expand_msg)
                time.sleep(1.5)
                st.rerun()
            else:
                st.error(expand_msg)

        new_loc = st.text_input("Target Locations (comma separated)", loc_str)
        new_platforms = st.multiselect("Active Job Boards", ["Daleel Madani", "UN Careers", "ReliefWeb", "LinkedIn", "Bayt.com", "EURAXESS"], default=selected_platforms)
        un_username = settings.get("un_username", "")
        un_password = settings.get("un_password", "")
        gemini_api_key = settings.get("gemini_api_key", "")
        col_api_1, col_api_2 = st.columns([2, 1])
        with col_api_1:
            new_gemini_key = st.text_input("Gemini API Key (optional)", gemini_api_key, type="password")
        with col_api_2:
            model_options = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash", "gemini-pro-latest", "gemini-2.5-pro"]
            selected_model = st.selectbox(
                "Gemini Model",
                options=model_options,
                index=model_options.index(settings.get("gemini_model", "gemini-flash-latest"))
            )

        # Toggles for AI and Scheduler
        col_toggles_1, col_toggles_2 = st.columns(2)
        with col_toggles_1:
            ai_enabled = st.toggle("Enable AI Evaluation & Matching", value=settings.get("ai_enabled", True))
        with col_toggles_2:
            scheduler_enabled = st.toggle("Enable Daily Auto-Scan (8:00 AM)", value=settings.get("scheduler_enabled", False))

        keyword_mode = st.radio(
            "Keyword Match Logic",
            options=["OR", "AND"],
            index=0 if settings.get("keyword_mode", "OR") == "OR" else 1,
            horizontal=True,
            help="OR: match jobs containing ANY keyword. AND: match jobs containing ALL keywords (stricter)."
        )

        st.markdown("---")
        st.markdown("**Upload Resume**")
        profile_summary = settings.get("profile_summary", "")
        if profile_summary:
            st.info(f"**Current Extracted Profile:** {profile_summary}")

        uploaded_file = st.file_uploader("Upload Resume to auto-generate profile and keywords (PDF)", type=["pdf"])

        if uploaded_file is not None and new_gemini_key:
            file_bytes = uploaded_file.read()
            file_hash = str(len(file_bytes))
            if st.session_state.get("processed_file_hash") != file_hash:
                with st.spinner("Extracting text and analyzing resume..."):
                    text = extract_text_from_pdf(file_bytes)
                    if text:
                        analysis, error_msg = analyze_resume_text(text, new_gemini_key, selected_model)
                        if analysis:
                            st.session_state["processed_file_hash"] = file_hash
                            parsed_kw = analysis.get("keywords", [])
                            extracted_summary = analysis.get("profile_summary", "")

                            try:
                                settings["keywords"] = parsed_kw
                                settings["profile_summary"] = extracted_summary
                                settings["gemini_api_key"] = new_gemini_key
                                settings["gemini_model"] = selected_model
                                with open("settings.json", "w") as f:
                                    json.dump(settings, f, indent=2)
                                st.success("Resume parsed and keywords updated!")
                                time.sleep(1.5)
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Error saving settings: {ex}")
                        else:
                            st.error(f"AI analysis of resume failed: {error_msg}")
                    else:
                        st.error("Could not extract text from this PDF file.")

        if st.button("Save Settings"):
            parsed_kw = [k.strip() for k in new_kw.split(",") if k.strip()]
            parsed_loc = [l.strip() for l in new_loc.split(",") if l.strip()]

            try:
                with open("settings.json", "w") as f:
                    json.dump({
                        "keywords": parsed_kw,
                        "locations": parsed_loc,
                        "platforms": new_platforms,
                        "un_username": un_username,
                        "un_password": un_password,
                        "gemini_api_key": new_gemini_key,
                        "profile_summary": settings.get("profile_summary", ""),
                        "ai_enabled": ai_enabled,
                        "scheduler_enabled": scheduler_enabled,
                        "keyword_mode": keyword_mode,
                        "gemini_model": selected_model
                    }, f, indent=2)
                st.toast("Settings saved!")
                time.sleep(1)
                st.rerun()
            except Exception as se:
                st.error(f"Could not save settings: {se}")

    # Main Action Button
    col_scrape, col_clear, col_info = st.columns([3, 3, 4])
    with col_scrape:
        trigger_scrape = st.button("Scan Job Boards", use_container_width=True)
    with col_clear:
        trigger_clear = st.button("Clear Results", use_container_width=True)

    if trigger_clear:
        try:
            db.clear_all_jobs()
            st.toast("Results cleared!")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Could not clear results: {e}")

    # Render Scan Logs if they exist in session state
    if st.session_state.get("scan_logs"):
        with st.expander("Scan Logs", expanded=True):
            st.code(st.session_state["scan_logs"])

    # Load data
    try:
        jobs_df = db.get_all_jobs_df()
    except Exception as e:
        st.error(f"Error loading jobs: {e}")
        jobs_df = pd.DataFrame()

    # Trigger action
    if trigger_scrape and not st.session_state.get("running"):
        st.session_state["scan_logs"] = ""
        st.session_state["log_lines"] = []

        # Resolve virtual environment python if it exists, otherwise fall back to system python
        venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")
        python_bin = venv_python if os.path.exists(venv_python) else sys.executable

        try:
            process = subprocess.Popen(
                [python_bin, "-u", "scraper.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            # Non-blocking reader thread
            import threading
            def log_reader(proc, lines_list):
                try:
                    for line in iter(proc.stdout.readline, ""):
                        if line:
                            lines_list.append(line.strip())
                except Exception:
                    pass
                finally:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass

            reader_thread = threading.Thread(target=log_reader, args=(process, st.session_state["log_lines"]))
            reader_thread.daemon = True
            reader_thread.start()

            st.session_state["process"] = process
            st.session_state["running"] = True
            st.rerun()
        except Exception as ex:
            st.error(f"Failed to start scraper: {ex}")

    if st.session_state.get("running"):
        scan_header = "Scanning Job Boards..." if not USE_EMOJIS else "Scanning Job Boards... ⚡"
        st.subheader(scan_header)

        # Stop button
        if st.button("Stop Search", type="primary"):
            proc = st.session_state.get("process")
            if proc:
                try:
                    proc.terminate()
                    proc.wait()
                except Exception:
                    pass
            st.session_state["running"] = False
            st.session_state["scan_logs"] = "\n".join(st.session_state.get("log_lines", [])) + "\n[System] Scan stopped by user."
            if "process" in st.session_state:
                del st.session_state["process"]
            st.toast("Search stopped!")
            time.sleep(1)
            st.rerun()

        log_placeholder = st.empty()
        lines = st.session_state.get("log_lines", [])
        log_placeholder.code("\n".join(lines[-20:]))

        st.markdown("**Live Matches Found**")
        matches_placeholder = st.empty()
        try:
            live_df = db.get_all_jobs_df()
            if not live_df.empty:
                live_rows = []
                for _, row in live_df.iterrows():
                    desc = row.get('Description', 'No description available.')
                    if pd.isna(desc): desc = 'No description available.'
                    deadline = row.get('Deadline', 'N/A')
                    if pd.isna(deadline): deadline = 'N/A'
                    score = row.get('Match Score', '')
                    score_str = f"{int(score)}%" if not pd.isna(score) and score != "" and str(score).replace('.','',1).isdigit() else ""
                    reason = row.get('Match Reason', '')
                    reason_str = reason if not pd.isna(reason) else ""
                    reqs = row.get('Key Requirements', '')
                    reqs_str = reqs if not pd.isna(reqs) else ""

                    live_rows.append(
                        f"<tr>"
                        f"<td><span class='source-tag'>[{row['Platform']}]</span></td>"
                        f"<td><strong>{row['Title']}</strong></td>"
                        f"<td>{row['Location']}</td>"
                        f"<td style='font-size: 0.8rem; color: var(--text-muted);'>{make_expandable_text(desc, 60)}</td>"
                        f"<td style='font-size: 0.8rem;'>{deadline}</td>"
                        f"<td>{score_str}</td>"
                        f"<td>{make_expandable_text(reason_str, 60)}</td>"
                        f"<td>{make_expandable_text(reqs_str, 60)}</td>"
                        f"<td><a href='{row['URL']}' target='_blank' class='job-link'>Apply</a></td>"
                        f"</tr>"
                    )
                live_html = (
                    f"<table class='job-table'>"
                    f"<thead><tr>"
                    f"<th style='width: 12%;'>Source</th>"
                    f"<th style='width: 25%;'>Job Title</th>"
                    f"<th style='width: 15%;'>Location</th>"
                    f"<th>Description</th>"
                    f"<th style='width: 13%;'>Deadline</th>"
                    f"<th style='width: 8%;'>Score</th>"
                    f"<th style='width: 20%;'>Reason</th>"
                    f"<th style='width: 20%;'>Key Requirements</th>"
                    f"<th style='width: 10%;'>Link</th>"
                    f"</tr></thead>"
                    f"<tbody>{''.join(live_rows)}</tbody>"
                    f"</table>"
                )
                matches_placeholder.markdown(live_html, unsafe_allow_html=True)
        except Exception:
            pass

        # Poll process status
        proc = st.session_state.get("process")
        if proc:
            rc = proc.poll()
            if rc is not None:
                st.session_state["running"] = False
                st.session_state["scan_logs"] = "\n".join(st.session_state.get("log_lines", []))
                if "process" in st.session_state:
                    del st.session_state["process"]
                if rc == 0:
                    st.toast("Scan complete!")
                else:
                    st.error("Error executing scraper.")
                time.sleep(1)
                st.rerun()
            else:
                time.sleep(1)
                st.rerun()

    # Render Job Table or Empty State
    if jobs_df.empty:
        st.markdown('<div style="color: var(--text-muted); font-size: 0.85rem; padding: 2rem 0;">No matched jobs found. Click "Scan Job Boards" to search.</div>', unsafe_allow_html=True)
    else:
        # Ensure Status column exists in jobs_df
        if "Status" not in jobs_df.columns:
            jobs_df["Status"] = "New"

        # Ensure Match Score is numeric for filtering
        jobs_df["Match Score"] = pd.to_numeric(jobs_df["Match Score"], errors="coerce").fillna(0).astype(int)

        # Score threshold slider + sort controls side by side
        col_filter, col_sort = st.columns([3, 2])
        with col_filter:
            min_score = st.slider(
                "Minimum Match Score",
                min_value=0, max_value=100, value=0, step=5,
                format="%d%%",
                help="Hide jobs below this AI match score. (The downloaded CSV will still contain all matches.)"
            )
        with col_sort:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            sort_by = st.selectbox(
                "Sort by",
                options=["Match Score ↓", "Deadline ↑", "Platform A–Z", "Date Added ↓"],
                index=0,
                label_visibility="collapsed"
            )

        filtered_df = jobs_df[jobs_df["Match Score"] >= min_score].copy()

        # Apply sort
        def sort_dataframe(df):
            if df.empty:
                return df
            if sort_by == "Match Score ↓":
                return df.sort_values("Match Score", ascending=False)
            elif sort_by == "Deadline ↑":
                from dateutil import parser as dparser
                def parse_deadline(val):
                    try:
                        return dparser.parse(str(val), dayfirst=False)
                    except Exception:
                        return pd.Timestamp.max
                df = df.copy()
                df["_deadline_sort"] = df["Deadline"].apply(parse_deadline)
                df = df.sort_values("_deadline_sort").drop(columns=["_deadline_sort"])
                return df
            elif sort_by == "Platform A–Z":
                return df.sort_values("Platform")
            else:  # Date Added ↓ — show newest matches first
                return df.iloc[::-1]

        filtered_df = sort_dataframe(filtered_df)

        # Group jobs by status (on filtered + sorted set)
        new_jobs = filtered_df[filtered_df["Status"] == "New"]
        applied_jobs = filtered_df[filtered_df["Status"] == "Applied"]
        archived_jobs = filtered_df[filtered_df["Status"] == "Archived"]

        # Download button always exports full unfiltered dataset
        csv_data = jobs_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Results (CSV)",
            data=csv_data,
            file_name="gesamtkunstwerk_job_matches.csv",
            mime="text/csv",
            use_container_width=True
        )
        st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)

        # Define CRM status tabs
        tab_new_label = f"New Matches ({len(new_jobs)})" if not USE_EMOJIS else f"New Matches \U0001F3AF ({len(new_jobs)})"
        tab_applied_label = f"Applied ({len(applied_jobs)})" if not USE_EMOJIS else f"Applied \U0001F4DD ({len(applied_jobs)})"
        tab_archived_label = f"Archived ({len(archived_jobs)})" if not USE_EMOJIS else f"Archived \U0001F4C1 ({len(archived_jobs)})"
        tab_new, tab_applied, tab_archived = st.tabs([
            tab_new_label,
            tab_applied_label,
            tab_archived_label
        ])

        # Card rendering function
        def render_job_card(row, idx, tab_name):
            platform = row["Platform"]
            title = row["Title"]
            location = row["Location"]
            desc = row.get("Description", "No description available.")
            if pd.isna(desc): desc = "No description available."
            deadline = row.get("Deadline", "N/A")
            if pd.isna(deadline): deadline = "N/A"
            url = row["URL"]

            score = row.get("Match Score", 0)
            try:
                score_val = int(score)
            except Exception:
                score_val = 0

            score_badge_class = "badge-score-high" if score_val >= 85 else "badge-score"

            reason = row.get("Match Reason", "No reason provided.")
            if pd.isna(reason): reason = "No reason provided."
            reqs = row.get("Key Requirements", "")
            if pd.isna(reqs): reqs = ""

            card_html = f"""
            <div class="job-card">
                <div class="card-header">
                    <h4 class="card-title">
                        <a href="{url}" target="_blank">{title}</a>
                    </h4>
                    <div>
                        <span class="badge {score_badge_class}">{score_val}% Match</span>
                    </div>
                </div>
                <div class="card-meta">
                    <span class="badge badge-source">[{platform}]</span>
                    <span>{"Location: " if not USE_EMOJIS else "\U0001F4CD "}{location}</span>
                    <span>{"Deadline: " if not USE_EMOJIS else "\U0001F4C5 Deadline: "}{deadline}</span>
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem;">
                    <strong>Reason:</strong> {make_expandable_text(reason, 60)}
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem;">
                    <strong>Key Requirements:</strong> {make_expandable_text(reqs, 60)}
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem;">
                    <strong>Description:</strong> {make_expandable_text(desc, 60)}
                </div>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)

            # Action buttons row
            col1, col2, col_spacer = st.columns([3, 3, 6])
            with col1:
                if tab_name == "new":
                    if st.button("Mark as Applied", key=f"btn_apply_{tab_name}_{idx}", use_container_width=True):
                        update_job_status(url, "Applied")
                elif tab_name in ("applied", "archived"):
                    if st.button("Move to New", key=f"btn_new_{tab_name}_{idx}", use_container_width=True):
                        update_job_status(url, "New")
            with col2:
                if tab_name in ("new", "applied"):
                    if st.button("Archive", key=f"btn_archive_{tab_name}_{idx}", use_container_width=True):
                        update_job_status(url, "Archived")
                elif tab_name == "archived":
                    if st.button("Delete", key=f"btn_delete_{tab_name}_{idx}", use_container_width=True):
                        delete_job_by_url(url)
            st.markdown("<div style='margin-bottom: 1.5rem; border-bottom: 1px solid var(--border-subtle);'></div>", unsafe_allow_html=True)

        with tab_new:
            if new_jobs.empty:
                st.markdown("<div style='color: var(--text-muted); font-size: 0.85rem; padding: 1rem 0;'>No new matches.</div>", unsafe_allow_html=True)
            else:
                for idx, row in new_jobs.reset_index().iterrows():
                    render_job_card(row, idx, "new")

        with tab_applied:
            if applied_jobs.empty:
                st.markdown("<div style='color: var(--text-muted); font-size: 0.85rem; padding: 1rem 0;'>No applications tracked yet.</div>", unsafe_allow_html=True)
            else:
                for idx, row in applied_jobs.reset_index().iterrows():
                    render_job_card(row, idx, "applied")

        with tab_archived:
            if archived_jobs.empty:
                st.markdown("<div style='color: var(--text-muted); font-size: 0.85rem; padding: 1rem 0;'>Archive is empty.</div>", unsafe_allow_html=True)
            else:
                for idx, row in archived_jobs.reset_index().iterrows():
                    render_job_card(row, idx, "archived")


with tab_custom:
    render_custom_tab()

# --- Background Scheduler Daemon ---
def run_scheduler_loop():
    print("[Scheduler] Started background daily scan scheduler thread.")
    last_run_date = None
    while True:
        # Check every 60 seconds
        time.sleep(60)
        try:
            if os.path.exists("settings.json"):
                with open("settings.json", "r") as f:
                    data = json.load(f)
                if not data.get("scheduler_enabled", False):
                    continue
            else:
                continue
                
            now = datetime.now()
            # Trigger if it's 8:00 AM (or later) and we haven't run today yet
            if now.hour >= 8 and last_run_date != now.date():
                print(f"[Scheduler] Triggering automatic daily scan at {now}")
                import subprocess
                proc = subprocess.Popen(["./venv/bin/python", "scraper.py"])
                last_run_date = now.date()
                # Wait up to 30 minutes, then kill if still running
                try:
                    proc.wait(timeout=1800)
                except subprocess.TimeoutExpired:
                    print("[Scheduler] Warning: scraper exceeded 30-minute timeout. Terminating.")
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except Exception as pe:
                    print(f"[Scheduler] Process wait error: {pe}")
        except Exception as e:
            print(f"[Scheduler] Error: {e}")

# Check if scheduler thread is already running to prevent duplicates on streamlit reruns
if not any(t.name == "DailyJobScheduler" for t in threading.enumerate()):
    scheduler_thread = threading.Thread(target=run_scheduler_loop, name="DailyJobScheduler")
    scheduler_thread.daemon = True
    scheduler_thread.start()
