"""
Check a production deploy or rollback against the running app.

    python scripts/check_deploy.py

Reads ADMIN_EMAIL / ADMIN_PASSWORD from ~/.career-intel/career-intel-keys.txt
(override with CAREER_INTEL_KEYS). CHECK_DEPLOY_URL overrides the address.
Prints no secrets and no IP addresses. Exits 1 if any check fails.

See DEPLOY.md, section 5.
"""

import ipaddress
import os
import subprocess
import sys
from pathlib import Path

import requests

DEFAULT_URL = "https://web-production-eab8b.up.railway.app"
BASE = os.environ.get("CHECK_DEPLOY_URL", DEFAULT_URL).rstrip("/")
API = f"{BASE}/api/v1"
KEYS = Path(
    os.environ.get("CAREER_INTEL_KEYS", Path.home() / ".career-intel" / "career-intel-keys.txt")
)
FAKE_IP = "198.51.100.77"  # TEST-NET-2, never a real client

failures = []


def report(label, ok, detail=""):
    mark = "ok  " if ok else "FAIL"
    print(f"[{mark}] {label}{': ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def credentials():
    if not KEYS.exists():
        sys.exit(f"Keys file not found: {KEYS}")
    values = {}
    for line in KEYS.read_text().splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    if not values.get("ADMIN_EMAIL") or not values.get("ADMIN_PASSWORD"):
        sys.exit("ADMIN_EMAIL / ADMIN_PASSWORD not found in the keys file.")
    return values["ADMIN_EMAIL"], values["ADMIN_PASSWORD"]


def local_head():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def kind(ip):
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid"
    return f"IPv{address.version}-{'public' if address.is_global else 'internal'}"


def forwarded(data):
    return [part.strip() for part in data["x_forwarded_for"].split(",") if part.strip()]


def main():
    print(f"Checking {BASE}\n")

    response = requests.get(f"{API}/health/ready/", timeout=30)
    checks = response.json().get("checks", {}) if response.ok else {}
    report("Ready", response.status_code == 200, ", ".join(f"{k} {v}" for k, v in checks.items()))

    email, password = credentials()
    response = requests.post(
        f"{API}/auth/login/", json={"email": email, "password": password}, timeout=30
    )
    token = response.json().get("access") if response.ok else None
    report("Admin login", bool(token), "" if token else f"status {response.status_code}")
    if not token:
        sys.exit(1)
    auth = {"Authorization": f"Bearer {token}"}

    response = requests.get(f"{API}/admin/dashboard/deploy-info/", headers=auth, timeout=30)
    if response.status_code == 404:
        report("Deploy info", False, "endpoint missing - this deploy predates it")
    else:
        info = response.json()
        release = info["release"]
        head = local_head()
        same = bool(release) and bool(head) and head.startswith(release[:7])
        detail = release[:7] or "unknown"
        if head:
            detail += " (matches local HEAD)" if same else f" (local HEAD is {head[:7]})"
        print(f"[info] Release: {detail}")
        report("Environment", info["environment"] == "production", info["environment"])
        print(f"[info] TRUSTED_PROXY_COUNT: {info['trusted_proxy_count']}")
        print(f"[info] Razorpay: {info['razorpay_mode']}")
        report("S3 uploads", info["s3_uploads"], "on" if info["s3_uploads"] else "off")
        report("Sentry", info["sentry_enabled"], "on" if info["sentry_enabled"] else "off")

    normal = requests.get(f"{API}/admin/dashboard/client-ip/", headers=auth, timeout=30).json()
    entries = forwarded(normal)
    chosen = normal["resolved_client_ip"]
    position = (
        f"entry {len(entries) - entries[::-1].index(chosen)} of {len(entries)}"
        if chosen in entries
        else "not in the list"
    )
    print(f"[info] X-Forwarded-For: {', '.join(kind(e) for e in entries) or 'empty'}")
    report(
        "Client IP uses the first (client) entry", bool(entries) and chosen == entries[0], position
    )

    fake = requests.get(
        f"{API}/admin/dashboard/client-ip/",
        headers={**auth, "X-Forwarded-For": FAKE_IP},
        timeout=30,
    ).json()
    report(
        "Client IP cannot be faked",
        fake["resolved_client_ip"] != FAKE_IP and fake["resolved_client_ip"] == chosen,
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
