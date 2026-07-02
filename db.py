import sqlite3
import os
import pandas as pd

DB_FILE = "jobs.db"
CSV_FILE = "profile_matched_jobs.csv"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            url TEXT PRIMARY KEY,
            platform TEXT,
            title TEXT,
            location TEXT,
            description TEXT,
            deadline TEXT,
            match_score INTEGER,
            match_reason TEXT,
            key_requirements TEXT,
            status TEXT DEFAULT 'New',
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    
    # Run automatic migration from CSV if CSV exists but DB is empty
    migrate_from_csv()

def migrate_from_csv():
    if not os.path.exists(CSV_FILE):
        return
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM jobs")
    count = c.fetchone()[0]
    
    if count == 0:
        print(f"[Database] Migrating existing jobs from {CSV_FILE} to SQLite...")
        try:
            df = pd.read_csv(CSV_FILE)
            for _, row in df.iterrows():
                url = row.get("URL")
                if not url or pd.isna(url):
                    continue
                
                # Check for NaN values in columns and replace with empty string / N/A
                platform = "" if pd.isna(row.get("Platform")) else str(row.get("Platform"))
                title = "" if pd.isna(row.get("Title")) else str(row.get("Title"))
                location = "" if pd.isna(row.get("Location")) else str(row.get("Location"))
                description = "" if pd.isna(row.get("Description")) else str(row.get("Description"))
                deadline = "N/A" if pd.isna(row.get("Deadline")) else str(row.get("Deadline"))
                
                try:
                    score = int(row.get("Match Score", 0))
                except (ValueError, TypeError):
                    score = 0
                    
                reason = "" if pd.isna(row.get("Match Reason")) else str(row.get("Match Reason"))
                reqs = "" if pd.isna(row.get("Key Requirements")) else str(row.get("Key Requirements"))
                status = "New" if pd.isna(row.get("Status")) else str(row.get("Status"))
                
                c.execute("""
                    INSERT OR REPLACE INTO jobs 
                    (url, platform, title, location, description, deadline, match_score, match_reason, key_requirements, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (url, platform, title, location, description, deadline, score, reason, reqs, status))
            conn.commit()
            print(f"[Database] Successfully migrated {len(df)} jobs from CSV.")
        except Exception as e:
            print(f"[Database] Error migrating from CSV: {e}")
            
    conn.close()

def save_job(job_data):
    """
    Saves a single job dictionary into the database.
    Expects keys: Platform, Title, Location, Description, Deadline, URL, Match Score, Match Reason, Key Requirements, Status
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        score = int(job_data.get("Match Score", 0))
    except (ValueError, TypeError):
        score = 0
        
    c.execute("""
        INSERT OR REPLACE INTO jobs 
        (url, platform, title, location, description, deadline, match_score, match_reason, key_requirements, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_data["URL"],
        job_data.get("Platform", ""),
        job_data.get("Title", ""),
        job_data.get("Location", ""),
        job_data.get("Description", ""),
        job_data.get("Deadline", "N/A"),
        score,
        job_data.get("Match Reason", ""),
        job_data.get("Key Requirements", ""),
        job_data.get("Status", "New")
    ))
    conn.commit()
    conn.close()

def get_all_jobs_df():
    """
    Returns all non-expired jobs as a pandas DataFrame formatted like the original CSV.
    """
    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT 
            platform as Platform,
            title as Title,
            location as Location,
            description as Description,
            deadline as Deadline,
            url as URL,
            match_score as [Match Score],
            match_reason as [Match Reason],
            key_requirements as [Key Requirements],
            status as Status
        FROM jobs
        WHERE status IN ('New', 'Applied', 'Archived')
        ORDER BY date_added DESC
    """, conn)
    conn.close()
    return df

def update_job_status(url, status):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))
    conn.commit()
    conn.close()

def delete_job(url):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM jobs WHERE url = ?", (url,))
    conn.commit()
    conn.close()

def prepare_new_scan():
    """
    Marks all 'New' jobs from previous runs as 'Expired' so they can serve as details cache,
    preserving Applied and Archived states.
    Also deletes Expired jobs older than 30 days to prevent excessive DB growth.
    """
    conn = get_db_connection()
    c = conn.cursor()
    # Mark old 'New' matches as 'Expired'
    c.execute("UPDATE jobs SET status = 'Expired' WHERE status = 'New'")
    
    # Delete expired jobs older than 30 days
    c.execute("DELETE FROM jobs WHERE status = 'Expired' AND date_added < datetime('now', '-30 days')")
    
    conn.commit()
    conn.close()

def get_cached_job(url):
    """
    Checks if a job URL is in the database and returns it if it has scraped description and AI evaluation.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT platform, title, location, description, deadline, url, match_score, match_reason, key_requirements, status 
        FROM jobs WHERE url = ?
    """, (url,))
    row = c.fetchone()
    conn.close()
    
    if row and row["description"] and row["match_score"] is not None:
        return {
            "Platform": row["platform"],
            "Title": row["title"],
            "Location": row["location"],
            "Description": row["description"],
            "Deadline": row["deadline"],
            "URL": row["url"],
            "Match Score": row["match_score"],
            "Match Reason": row["match_reason"],
            "Key Requirements": row["key_requirements"],
            "Status": row["status"]
        }
    return None

def write_db_to_csv():
    """Export all jobs to CSV for backup/download compatibility."""
    df = get_all_jobs_df()
    df.to_csv(CSV_FILE, index=False, encoding="utf-8")

def clear_all_jobs():
    """Wipes the database and removes backup CSV files."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM jobs")
    conn.commit()
    conn.close()
    if os.path.exists(CSV_FILE):
        try:
            os.remove(CSV_FILE)
        except Exception:
            pass
