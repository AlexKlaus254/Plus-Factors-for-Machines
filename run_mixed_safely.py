"""Run cells on Modal endpoints and always shut the endpoints down afterwards.

  py run_mixed_safely.py --all         whole grid (same and mixed arms)
  py run_mixed_safely.py               mixed-model cells only
  py run_mixed_safely.py --stop-only   stop endpoints and list what is running

Shutdown safeguards: endpoints are stopped in a `finally` block; a hard time limit
(--max-minutes); a one-time Windows scheduled task runs stop_modal.bat if this process dies;
and a final listing of Modal endpoints and apps.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from llm import load_env

HERE = Path(__file__).resolve().parent
ENDPOINTS = {
    "qwen": ("Qwen/Qwen3.6-27B-FP8", "MODAL_QWEN_URL"),
    "gemma4": ("google/gemma-4-26B-A4B-it", "MODAL_GEMMA_URL"),
}
PROVIDER_OF = {"qwen": "modal_qwen:", "gemma4": "modal_gemma:"}
TASK = "StopModalEndpoints_PlusFactors"
MODAL = [sys.executable, "-m", "modal"]
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")


def sh(args, check=False, capture=True, timeout=600, quiet=False):
    print("  >", " ".join(str(a) for a in args[2:] if a != "-m"))
    r = subprocess.run(args, capture_output=capture, text=True, timeout=timeout, env=ENV,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if capture and out.strip() and not quiet:
        print("   ", out.strip().replace("\n", "\n    ")[:1500])
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}")
    return r.returncode, out, (r.stdout or "")


def stop_all():
    print("\n=== Stopping Modal endpoints ===")
    for name in ENDPOINTS:
        for attempt in range(3):
            code, out, _ = sh(MODAL + ["endpoint", "stop", name, "-y"])
            if code == 0 or "not found" in out.lower() or "no endpoint" in out.lower():
                break
            time.sleep(5)
    print("\n=== Still running on Modal? (should list nothing for these endpoints) ===")
    sh(MODAL + ["endpoint", "list"])
    sh(MODAL + ["app", "list"])


def _ps(command):
    return sh(["powershell", "-NoProfile", "-Command", command])


def schedule_deadman(minutes):
    """One-time Windows scheduled task that runs stop_modal.bat later, even if this script dies."""
    if os.name != "nt":
        return
    bat = HERE / "stop_modal.bat"
    when = (dt.datetime.now() + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    code, _, _ = _ps(f"Register-ScheduledTask -TaskName '{TASK}' -Force "
                  f"-Action (New-ScheduledTaskAction -Execute '{bat}') "
                  f"-Trigger (New-ScheduledTaskTrigger -Once -At ([datetime]'{when}'))")
    if code == 0:
        print(f"   Dead-man switch set: stop_modal.bat runs at {when.replace('T', ' ')} unless this script finishes first.")
    else:
        print("   WARNING: could not set the dead-man switch. Keep this window open and watch the run.")


def remove_deadman():
    if os.name == "nt":
        _ps(f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false -ErrorAction SilentlyContinue")


def _urls(obj):
    """All https URLs in a JSON object or text, except links to the Modal dashboard."""
    text = json.dumps(obj) if not isinstance(obj, str) else obj
    return [u.rstrip("/").split("/v1")[0] for u in re.findall(r"https://[^\s\"'|]+", text)
            if not u.startswith("https://modal.com/")]


def find_url(name, deadline):
    """Poll 'modal endpoint info' until the endpoint has a URL (it gets one once provisioning ends)."""
    while time.time() < deadline:
        code, out, stdout = sh(MODAL + ["endpoint", "info", name, "--json"], quiet=True)
        try:
            data = json.loads(stdout)
        except ValueError:
            data = stdout or out
        urls = _urls(data)
        state = re.search(r'"?(?:state|status)"?\s*[:=]?\s*"?(\w+)', stdout or out, re.I)
        print(f"   {name}: state={state.group(1) if state else '?'} url={urls[0] if urls else '(not yet)'}")
        if urls:
            return urls[0]
        time.sleep(20)
    return None


def wait_ready(url, token, limit_s):
    t0 = time.time()
    while time.time() - t0 < limit_s:
        try:
            r = httpx.get(url + "/v1/models", headers={"Authorization": f"Bearer {token}"}, timeout=60)
            if r.status_code == 200:
                names = [m.get("id") for m in r.json().get("data", [])]
                return names
            print(f"   not ready yet (HTTP {r.status_code}); waiting...")
        except httpx.HTTPError:
            print("   not ready yet; waiting...")
        time.sleep(30)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=int, default=120)
    ap.add_argument("--stop-only", action="store_true")
    ap.add_argument("--endpoints", nargs="*", default=list(ENDPOINTS), help="which endpoints to create")
    ap.add_argument("--all", action="store_true", help="run the whole grid, not only the mixed cells")
    ap.add_argument("--run-concurrency", type=int, default=16)
    args = ap.parse_args()
    os.chdir(HERE)
    if args.stop_only:
        stop_all()
        remove_deadman()
        return

    load_env()
    token = os.environ.get("MODAL_PROXY_TOKEN")
    if not token or "." not in token:
        raise SystemExit("Set MODAL_PROXY_TOKEN=<token id>.<token secret> in compute.env first "
                         "(create one with: py -m modal workspace proxy-tokens create).")
    deadline = time.time() + args.max_minutes * 60
    schedule_deadman(args.max_minutes + 15)
    clean = False
    try:
        print("\n=== Creating endpoints (billing starts now) ===")
        use = {n: ENDPOINTS[n] for n in args.endpoints}
        for name, (model, _) in use.items():
            sh(MODAL + ["endpoint", "create", "--name", name, "--model", model], capture=False)
        env = dict(os.environ)
        for name, (model, var) in use.items():
            print(f"\n=== Waiting for '{name}' to finish provisioning (first start can take 10-30 min) ===")
            url = find_url(name, deadline)
            if not url:
                raise RuntimeError(f"Endpoint '{name}' got no URL before the time limit.")
            print(f"\n=== Waiting for '{name}' at {url} ===")
            names = wait_ready(url, token, max(60, deadline - time.time()))
            if names is None:
                raise RuntimeError(f"Endpoint '{name}' never became ready.")
            print(f"   ready; serves: {names}")
            wanted = [m.split(":", 1)[1] for m in json.loads((HERE / "experiment.json").read_text(encoding="utf-8"))["arms"]["mixed"]["models"]
                      if m.startswith(PROVIDER_OF[name])]
            if names and wanted and wanted[0] not in names:
                print(f"   NOTE: experiment.json uses '{wanted[0]}' but the endpoint serves {names}. "
                      "Fix the name in experiment.json -> arms -> mixed, then rerun this script.")
                raise RuntimeError("model name mismatch")
            env[var] = url
        print("\n=== Final warm-up: all endpoints must answer together ===")
        for _ in range(3):
            urls = {n: env[ENDPOINTS[n][1]] for n in use}
            states = {n: wait_ready(u, token, max(60, deadline - time.time())) for n, u in urls.items()}
            if any(v is None for v in states.values()):
                raise RuntimeError("An endpoint did not come back up before the time limit.")
            if all(wait_ready(u, token, 5) is not None for u in urls.values()):
                break
        print("   all endpoints warm")
        print("\n=== Running the mixed-model cells ===")
        cmd = [sys.executable, "run_experiment.py", "--run-concurrency", str(args.run_concurrency)]
        if not args.all:
            cmd += ["--only", "L0:mixed", "L3:mixed"]
        proc = subprocess.Popen(cmd, env=env)
        while proc.poll() is None:
            if time.time() > deadline:
                print("\n!!! Time limit reached: stopping the run (finished runs are kept; rerun later to resume).")
                proc.kill()
                break
            time.sleep(5)
        clean = proc.returncode == 0
    except KeyboardInterrupt:
        print("\nCtrl+C received.")
    except Exception as e:
        print(f"\n!!! {e}")
    finally:
        stop_all()
        remove_deadman()
        print("\n" + ("All done." if clean else "Stopped early; finished runs are saved. Rerun this script to resume.")
              + "\nCheck modal.com -> Usage to confirm nothing is running.")


if __name__ == "__main__":
    main()
