"""Launch Streamlit dashboard + a public tunnel.

Usage:
    python start_dashboard.py

What it does:
    1. Launches Streamlit on a local port.
    2. Opens a public tunnel (cloudflared if available, otherwise SSH via
       localhost.run which needs only OpenSSH, built into Windows).
    3. Prints the public URL and writes it to `.env` as DASHBOARD_URL so the
       Telegram bot shows an "Open Dashboard" button.

Requirements:
    - streamlit installed (in the venv)
    - optional cloudflared binary (cloudflared.exe in this folder or on PATH)
      https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
    - if cloudflared is not used: ssh (OpenSSH client, built into Windows 10+)
"""
import os
import re
import subprocess
import sys
import shutil
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")

# Local Streamlit server (default port)
STREAMLIT_PORT = os.getenv("STREAMLIT_PORT", "8501")

# cloudflared binary lookup order: local copy first, then PATH.
LOCAL_CLOUDFLARED = os.path.join(BASE_DIR, "cloudflared.exe")


def _locate_cloudflared() -> str:
    """Return the path to a cloudflared binary, or '' if not found."""
    if os.path.exists(LOCAL_CLOUDFLARED):
        return LOCAL_CLOUDFLARED
    found = shutil.which("cloudflared")
    return found or ""


def _update_env(url: str) -> None:
    """Write DASHBOARD_URL=<url> into .env (create/overwrite that line)."""
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = []
    found = False
    for line in lines:
        if line.startswith("DASHBOARD_URL="):
            out.append(f"DASHBOARD_URL={url}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"DASHBOARD_URL={url}")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"[start_dashboard] .env updated: DASHBOARD_URL={url}")


def _find_cloudflared_url(proc, max_wait: float = 25.0) -> str:
    """Scan cloudflared output for https://...trycloudflare.com URL."""
    start = time.time()
    while time.time() - start < max_wait:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.2)
            continue
        text = line.decode(errors="replace")
        m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", text)
        if m:
            return m.group(0)
    return ""


def _find_ssh_url(proc, max_wait: float = 30.0) -> str:
    """Scan localhost.run output for https://...lhr.life (or .lhr) URL."""
    start = time.time()
    while time.time() - start < max_wait:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.3)
            continue
        text = line.decode(errors="replace")
        m = re.search(r"https://[\w\-]+\.lhr\.life", text)
        if m:
            return m.group(0)
    return ""


def _url_is_ok(url: str, max_wait: float = 20.0) -> bool:
    """Check that a public URL actually returns HTTP 200.

    cloudflared can print a URL even if the network blocks Cloudflare
    (QUIC/UDP blocked => 530). We only trust a URL that really serves
    the dashboard.
    """
    import urllib.request
    start = time.time()
    while time.time() - start < max_wait:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "healthcheck"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            time.sleep(2)
    return False


def _launch_streamlit() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "dashboard/app.py",
         "--server.port", STREAMLIT_PORT, "--server.headless", "true"],
        cwd=BASE_DIR,
    )
    print(f"[start_dashboard] Streamlit running on port {STREAMLIT_PORT}", flush=True)
    return proc


def main() -> None:
    st_proc = _launch_streamlit()

    # --- Try cloudflared first (if binary present), then fall back to SSH ---
    cloudflared = _locate_cloudflared()
    url = ""
    tunnel = None

    if cloudflared:
        print("[start_dashboard] Trying cloudflared tunnel...", flush=True)
        tunnel = subprocess.Popen(
            [cloudflared, "tunnel", "--url", f"http://localhost:{STREAMLIT_PORT}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        url = _find_cloudflared_url(tunnel)
        if url:
            print(f"[start_dashboard] cloudflared URL: {url}", flush=True)
            print("[start_dashboard] Verifying cloudflared tunnel reachable...", flush=True)
            if not _url_is_ok(url):
                print("[start_dashboard] cloudflared URL not reachable (network blocks Cloudflare). "
                      "Switching to SSH tunnel...", flush=True)
                url = ""
            else:
                print("[start_dashboard] cloudflared tunnel OK", flush=True)

    if not url:
        if tunnel:
            print("[start_dashboard] cloudflared unavailable (network may block UDP/TCP). "
                  "Switching to SSH tunnel (localhost.run)...", flush=True)
            tunnel.terminate()
        print("[start_dashboard] Starting SSH tunnel via localhost.run...", flush=True)
        tunnel = subprocess.Popen(
            [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ServerAliveInterval=30",
                "-R", f"80:localhost:{STREAMLIT_PORT}",
                "nokey@localhost.run",
            ],
            stdout=subprocess.PIPE,
        )
        url = _find_ssh_url(tunnel)

    if url:
        print(f"\nPublic dashboard URL: {url}\n", flush=True)
        _update_env(url)
    else:
        print("⚠️ Could not obtain a public URL. Check the tunnel output manually.", flush=True)

    try:
        while st_proc.poll() is None and tunnel.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        st_proc.terminate()
        tunnel.terminate()


if __name__ == "__main__":
    main()