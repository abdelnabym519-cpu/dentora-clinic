#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_WORKER_URL = ""
ROOT = Path(__file__).resolve().parents[1]
SECRET_FILE = ROOT / ".license-dev" / "server.env"
ARCHIVE_DIR = ROOT / ".license-dev" / "customer-licenses"


def load_admin_key() -> str:
    value = os.getenv("LICENSE_ADMIN_API_KEY", "").strip()
    if value:
        return value

    if SECRET_FILE.exists():
        for line in SECRET_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("LICENSE_ADMIN_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value

    raise RuntimeError(
        "LICENSE_ADMIN_API_KEY was not found. Set it in the environment or keep the owner-only key in .license-dev/server.env"
    )


def worker_url() -> str:
    value = os.getenv("DENTORA_LICENSE_WORKER_URL", DEFAULT_WORKER_URL).strip().rstrip("/")
    if not value:
        raise RuntimeError("Set DENTORA_LICENSE_WORKER_URL to the deployed Dentora License Worker URL")
    return value


def api(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
        "X-Admin-Key": load_admin_key(),
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        worker_url() + path,
        data=data,
        method=method,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        detail = raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                detail = str(parsed.get("detail") or parsed)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Dentora License Server: {exc.reason}") from exc


def format_expiry(value: str | None) -> str:
    if not value:
        return "perpetual"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return value


def fetch_licenses() -> list[dict[str, Any]]:
    data = api("GET", "/admin/licenses")
    if not isinstance(data, list):
        raise RuntimeError("License server returned an invalid license list")
    return data


def show_licenses(items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    items = items if items is not None else fetch_licenses()
    if not items:
        print("No licenses found.")
        return items

    print()
    print("#  Customer                              Status       Expires      Active/Max")
    print("-" * 82)
    for index, item in enumerate(items, 1):
        customer = str(item.get("customer_name") or "")[:36]
        status = str(item.get("status") or "")[:12]
        expires = format_expiry(item.get("expires_at"))[:12]
        active = int(item.get("active_activations") or 0)
        maximum = int(item.get("max_activations") or 0)
        print(f"{index:<2} {customer:<36} {status:<12} {expires:<12} {active}/{maximum}")
    print()
    return items


def choose_license() -> dict[str, Any]:
    items = show_licenses()
    if not items:
        raise RuntimeError("There are no licenses to select")

    while True:
        raw = input("Choose license number: ").strip()
        try:
            index = int(raw)
        except ValueError:
            print("Enter a valid number.")
            continue
        if 1 <= index <= len(items):
            return items[index - 1]
        print("Number is out of range.")


def copy_to_clipboard(value: str) -> bool:
    command = shutil.which("clip.exe") or shutil.which("clip")
    if not command:
        return False
    try:
        subprocess.run([command], input=value, text=True, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def save_created_license(result: dict[str, Any]) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{result['id']}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def create_license() -> None:
    print("\nCreate license")
    customer = input("Customer / clinic name: ").strip()
    if not customer:
        raise RuntimeError("Customer name is required")

    plan = input("Plan [standard]: ").strip() or "standard"
    duration_raw = input("Duration days [365] or type permanent: ").strip() or "365"
    max_raw = input("Maximum active installations [1]: ").strip() or "1"
    features_raw = input("Features [core,booking]: ").strip() or "core,booking"

    body: dict[str, Any] = {
        "customer_name": customer,
        "plan": plan,
        "max_activations": int(max_raw),
        "features": [x.strip() for x in features_raw.split(",") if x.strip()],
    }
    if duration_raw.lower() not in {"permanent", "perpetual"}:
        body["duration_days"] = int(duration_raw)

    result = api("POST", "/admin/licenses", body)
    if not isinstance(result, dict) or not result.get("license_key"):
        raise RuntimeError("License server did not return a license key")

    saved = save_created_license(result)
    copied = copy_to_clipboard(str(result["license_key"]))

    print("\nLicense created successfully.")
    print("Customer:", result.get("customer_name"))
    print("Plan:", result.get("plan"))
    print("Expires:", format_expiry(result.get("expires_at")))
    print("Key prefix:", result.get("key_prefix"))
    print("Full key: HIDDEN")
    print("Saved locally:", saved)
    if copied:
        print("Full key copied to Windows clipboard.")
    else:
        print("Clipboard copy was unavailable; retrieve the key from the saved owner-only JSON file.")


def renew_license() -> None:
    item = choose_license()
    raw = input("Extend by days [365]: ").strip() or "365"
    result = api(
        "POST",
        f"/admin/licenses/{item['id']}/renew",
        {"duration_days": int(raw)},
    )
    print("Renewed successfully.")
    print("Previous expiry:", format_expiry(result.get("previous_expires_at")))
    print("New expiry:", format_expiry(result.get("expires_at")))


def change_status(action: str) -> None:
    item = choose_license()
    result = api("POST", f"/admin/licenses/{item['id']}/{action}")
    print("Server status:", result.get("status") if isinstance(result, dict) else result)


def fetch_activations(license_id: str) -> list[dict[str, Any]]:
    data = api("GET", f"/admin/licenses/{license_id}/activations")
    if not isinstance(data, list):
        raise RuntimeError("License server returned an invalid activation list")
    return data


def show_activations() -> None:
    item = choose_license()
    activations = fetch_activations(str(item["id"]))
    if not activations:
        print("No activations found.")
        return

    print()
    for index, activation in enumerate(activations, 1):
        status = "REVOKED" if activation.get("revoked_at") else "ACTIVE"
        print(
            f"{index}. {status:<7}  installation={activation.get('installation_id')}  "
            f"last_seen={activation.get('last_seen_at')}"
        )
    print()


def revoke_activation() -> None:
    item = choose_license()
    activations = fetch_activations(str(item["id"]))
    active = [x for x in activations if not x.get("revoked_at")]
    if not active:
        print("There are no active installations to revoke.")
        return

    print()
    for index, activation in enumerate(active, 1):
        print(f"{index}. installation={activation.get('installation_id')} last_seen={activation.get('last_seen_at')}")

    raw = input("Choose active installation to revoke: ").strip()
    index = int(raw)
    if index < 1 or index > len(active):
        raise RuntimeError("Activation number is out of range")

    chosen = active[index - 1]
    confirm = input("Type REVOKE to confirm: ").strip()
    if confirm != "REVOKE":
        print("Cancelled.")
        return

    result = api("POST", f"/admin/activations/{chosen['id']}/revoke")
    print("Server status:", result.get("status") if isinstance(result, dict) else result)



def set_ai_feature(enabled: bool) -> None:
    item = choose_license()

    features = {
        str(value).strip().lower()
        for value in (item.get("features") or [])
        if str(value).strip()
    }

    before = "ai" in features

    if enabled:
        features.add("ai")
    else:
        features.discard("ai")

    result = api(
        "POST",
        f"/admin/licenses/{item['id']}/features",
        {"features": sorted(features)},
    )

    state = "ENABLED" if enabled else "DISABLED"

    print()
    print(f"AI feature: {state}")
    print("Customer:", item.get("customer_name"))
    print(
        "Features:",
        ",".join(result.get("features") or [])
        if isinstance(result, dict)
        else ",".join(sorted(features)),
    )

    if before == enabled:
        print("No feature change was necessary.")
    else:
        print("The client will receive the change on its next license refresh.")


def menu() -> None:
    print("Dentora License Administration")
    print("Server:", worker_url())

    while True:
        print(
            "\n"
            "1) List licenses\n"
            "2) Create new license\n"
            "3) Renew / extend subscription\n"
            "4) Suspend license\n"
            "5) Resume license\n"
            "6) View activations\n"
            "7) Revoke an installation\n"
            "8) Enable AI for customer\n"
            "9) Disable AI for customer\n"
            "0) Exit"
        )
        choice = input("Select: ").strip()
        try:
            if choice == "1":
                show_licenses()
            elif choice == "2":
                create_license()
            elif choice == "3":
                renew_license()
            elif choice == "4":
                change_status("suspend")
            elif choice == "5":
                change_status("resume")
            elif choice == "6":
                show_activations()
            elif choice == "7":
                revoke_activation()
            elif choice == "8":
                set_ai_feature(True)
            elif choice == "9":
                set_ai_feature(False)
            elif choice == "0":
                return
            else:
                print("Unknown option.")
        except (RuntimeError, ValueError) as exc:
            print("ERROR:", exc)


def main() -> int:
    try:
        load_admin_key()
        menu()
        return 0
    except RuntimeError as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
