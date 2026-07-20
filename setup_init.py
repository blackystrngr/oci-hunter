"""
setup_init.py - Cross-platform launcher (Windows / macOS / Linux).

Pure-Python replacement for setup_init.sh. Installs dependencies straight
into the CURRENT Python interpreter (no virtual environment, per design),
then launches main.py and watches its log files / exit status, sending
Discord and/or Telegram notifications along the way if configured.

Usage:
    python setup_init.py            # first run: installs deps, then launches
    python setup_init.py rerun      # skip the dependency install step
"""

import subprocess
import sys
import time
import urllib.request
import urllib.parse
import json as _json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Minimal .env reader (stdlib only) - deliberately NOT using python-dotenv
# here, since on a first run this script executes *before* requirements.txt
# has been installed.
# ---------------------------------------------------------------------------
def read_env_file(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


ENV = read_env_file(BASE_DIR / "oci.env")
DISCORD_WEBHOOK = ENV.get("DISCORD_WEBHOOK", "")
TELEGRAM_TOKEN = ENV.get("TELEGRAM_TOKEN", "")
TELEGRAM_USER_ID = ENV.get("TELEGRAM_USER_ID", "")


def _post(url, data):
    try:
        req = urllib.request.Request(
            url,
            data=_json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:  # notifications should never crash the script
        print(f"[notify] failed to reach {url}: {e}")


def send_discord_message(message):
    if DISCORD_WEBHOOK:
        _post(DISCORD_WEBHOOK, {"content": message})


def send_telegram_message(message):
    if TELEGRAM_TOKEN and TELEGRAM_USER_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        params = urllib.parse.urlencode({"chat_id": TELEGRAM_USER_ID, "text": message})
        try:
            urllib.request.urlopen(f"{url}?{params}", timeout=15)
        except Exception as e:
            print(f"[notify] telegram failed: {e}")


def send_notification(message):
    send_discord_message(message)
    send_telegram_message(message)


# ---------------------------------------------------------------------------
# Step 0: clean up old logs from a previous run
# ---------------------------------------------------------------------------
def clean_old_logs():
    log_patterns = ["*.log"]
    removed = False
    for pattern in log_patterns:
        for log_file in BASE_DIR.glob(pattern):
            log_file.unlink()
            removed = True
    if removed:
        print("Previous log files deleted.")


# ---------------------------------------------------------------------------
# Step 1: install dependencies directly against the running interpreter.
# No venv is created - this intentionally installs into whatever Python
# you launched this script with.
# ---------------------------------------------------------------------------
def install_dependencies():
    print(f"Installing dependencies with {sys.executable} (no virtual environment)...")
    pip_cmd = [sys.executable, "-m", "pip"]
    subprocess.run(pip_cmd + ["install", "--upgrade", "pip"], check=True)
    subprocess.run(pip_cmd + ["install", "wheel", "setuptools"], check=True)
    subprocess.run(pip_cmd + ["install", "-r", str(BASE_DIR / "requirements.txt")], check=True)


# ---------------------------------------------------------------------------
# Step 2: launch main.py as a background/child process and monitor it.
# ---------------------------------------------------------------------------
def launch_main():
    kwargs = {}
    if sys.platform == "win32":
        # Give the child its own process group on Windows so Ctrl+C in
        # this console doesn't automatically also signal the child; we
        # handle stopping it ourselves in the except block below.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    return subprocess.Popen(
        [sys.executable, str(BASE_DIR / "main.py")],
        cwd=str(BASE_DIR),
        **kwargs,
    )


def file_has_content(name):
    path = BASE_DIR / name
    return path.is_file() and path.stat().st_size > 0


def check_initial_status():
    """Mirrors the original bash script's post-launch log inspection."""
    time.sleep(5)  # give main.py a moment to run and write logs

    if file_has_content("ERROR_IN_CONFIG.log"):
        print("Error occurred, check ERROR_IN_CONFIG.log and rerun the script")
        send_notification("\U0001F615 Uh-oh! There's an error in the config. Check ERROR_IN_CONFIG.log and give it another shot!")
        return False

    if file_has_content("INSTANCE_CREATED"):
        print("Instance created, or the Free Tier limit was already reached. Check 'INSTANCE_CREATED'.")
        send_notification("\U0001F38A Great news! An instance was created, or we've hit the Free Tier limit. Check the 'INSTANCE_CREATED' file for details!")
        return True

    if file_has_content("launch_instance.log"):
        print("Script is running successfully")
        send_notification("\U0001F44D All systems go! The script is running smoothly.")
        return True

    print("Couldn't find any logs, waiting 60s before checking again")
    time.sleep(60)

    if file_has_content("launch_instance.log"):
        print("Script is running successfully")
        send_notification("\U0001F44D Good news! The script is up and running after a short delay.")
        return True

    print("Unhandled exception occurred, or the script is still starting up.")
    send_notification("\U0001F631 Yikes! No logs showed up after a minute - check the console output.")
    return True


def monitor(proc):
    """Wait for main.py to finish, or handle Ctrl+C by stopping it."""
    try:
        while proc.poll() is None:
            time.sleep(60)
        send_notification("\U0001F3C1 The OCI Instance Creation Script has finished running.")
    except KeyboardInterrupt:
        print("\nInterrupted - stopping main.py ...")
        send_notification("\U0001F6D1 Heads up! The OCI Instance Creation Script was interrupted or stopped.")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)


def main():
    rerun = len(sys.argv) > 1 and sys.argv[1] == "rerun"

    clean_old_logs()

    if not rerun:
        install_dependencies()

    proc = launch_main()
    print(f"main.py launched (pid={proc.pid})")

    still_running = check_initial_status()
    if not still_running:
        # Config error - main.py will have exited already.
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
        sys.exit(1)

    monitor(proc)


if __name__ == "__main__":
    main()
