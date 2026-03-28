"""Launch both OpenAlgo (Flask :5000) and AAUM Intelligence (FastAPI :8080).

Requires AAUM to be installed in the same Python environment, OR set AAUM_DIR
to an AAUM project directory with its own venv and use a separate terminal.

Recommended development workflow (separate venvs):
  Terminal 1: cd C:/Users/sakth/Desktop/aaum && uvicorn aaum.server:app --port 8080
  Terminal 2: cd D:/openalgo && uv run app.py

Production (AAUM in same venv as OpenAlgo):
  uv run start_with_aaum.py
"""
import os
import signal
import subprocess
import sys
import time

AAUM_DIR = os.getenv("AAUM_DIR", os.path.join(os.path.dirname(__file__), "aaum_intelligence"))
AAUM_PORT = int(os.getenv("AAUM_PORT", "8080"))


def main():
    if not os.path.isdir(AAUM_DIR):
        print(f"[start_with_aaum] ERROR: AAUM directory not found: {AAUM_DIR!r}")
        print()
        print("Options:")
        print(f"  1. Copy AAUM source to {AAUM_DIR}/")
        print("  2. Set AAUM_DIR env var to your AAUM project path")
        print("  3. Run AAUM separately (recommended for development):")
        print("       Terminal 1: cd C:/Users/sakth/Desktop/aaum && uvicorn aaum.server:app --port 8080")
        print("       Terminal 2: uv run app.py")
        sys.exit(1)

    print(f"[start_with_aaum] Starting AAUM FastAPI on :{AAUM_PORT} from {AAUM_DIR!r} ...")
    aaum_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "aaum.server:app",
         "--host", "0.0.0.0", "--port", str(AAUM_PORT), "--log-level", "info"],
        cwd=AAUM_DIR,
    )

    print("[start_with_aaum] Waiting 4 seconds for AAUM to initialize ...")
    time.sleep(4)

    if aaum_proc.poll() is not None:
        print("[start_with_aaum] ERROR: AAUM process exited immediately. Check AAUM logs above.")
        sys.exit(1)

    print("[start_with_aaum] Starting OpenAlgo Flask on :5000 ...")
    openalgo_proc = subprocess.Popen([sys.executable, "app.py"])

    def shutdown(sig, frame):
        print("\n[start_with_aaum] Shutting down ...")
        openalgo_proc.terminate()
        aaum_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[start_with_aaum] Both processes running. Ctrl+C to stop.")
    openalgo_proc.wait()


if __name__ == "__main__":
    main()
