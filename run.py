import os
import sys
import subprocess

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(base_dir, "venv", "bin", "python")
    
    if os.path.exists(venv_python):
        print(f"[System] Launcher: Using virtual environment Python: {venv_python}")
        cmd = [venv_python, "-m", "streamlit", "run", os.path.join(base_dir, "app.py")]
    else:
        print("[Warning] Launcher: Virtual environment not found. Falling back to system python3...")
        cmd = ["python3", "-m", "streamlit", "run", os.path.join(base_dir, "app.py")]
        
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n[System] Launcher: App stopped.")
    except Exception as e:
        print(f"\n[Error] Launcher: Failed to run Streamlit: {e}")

if __name__ == "__main__":
    main()
