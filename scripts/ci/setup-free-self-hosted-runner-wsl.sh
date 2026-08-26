#!/usr/bin/env bash
set -euo pipefail
umask 077

REPO="abdelnabym519-cpu/dentora-clinic"
REPO_URL="https://github.com/${REPO}"
RUNNER_LABEL="dentora-ci"
RUNNER_DIR="${HOME}/actions-runner-dentora"
RUNNER_NAME="${HOSTNAME:-dentora-wsl}-dentora-ci"
PLAYWRIGHT_VERSION="1.59.1"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v tar >/dev/null 2>&1 || die "tar is required"
command -v docker >/dev/null 2>&1 || die "Linux docker CLI is required inside WSL"
command -v powershell.exe >/dev/null 2>&1 || die "This bootstrap must run inside WSL on Windows"

docker info >/dev/null 2>&1 || die "Docker is not reachable inside WSL. Docker Desktop WSL integration must be enabled."

printf 'Installing Linux prerequisites for the runner and Playwright...\n'
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl git jq nodejs npm python3 tar

# The CI job keeps its project-pinned browser install. We install only the
# OS packages here so Playwright never needs interactive sudo during a job.
sudo npx -y "playwright@${PLAYWRIGHT_VERSION}" install-deps chromium

mkdir -p "${RUNNER_DIR}"
cd "${RUNNER_DIR}"

release_json="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
runner_version="$(
  python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))' \
    <<<"${release_json}"
)"
archive="actions-runner-linux-x64-${runner_version}.tar.gz"
asset_url="https://github.com/actions/runner/releases/download/v${runner_version}/${archive}"
asset_digest="$(
  python3 -c 'import json,sys
name=sys.argv[1]
data=json.load(sys.stdin)
print(next((a.get("digest") or "" for a in data.get("assets", []) if a.get("name")==name), ""))' \
    "${archive}" <<<"${release_json}"
)"

if [[ ! -x "./config.sh" ]]; then
  printf 'Downloading GitHub Actions runner %s...\n' "${runner_version}"
  curl -fL --retry 3 --retry-delay 2 "${asset_url}" -o "${archive}"

  if [[ "${asset_digest}" == sha256:* ]]; then
    printf '%s  %s\n' "${asset_digest#sha256:}" "${archive}" | sha256sum -c -
  else
    printf 'WARNING: GitHub release metadata did not expose an asset digest; continuing over HTTPS.\n' >&2
  fi

  tar xzf "${archive}"
  rm -f "${archive}"
  sudo ./bin/installdependencies.sh
fi

if [[ ! -f ".runner" ]]; then
  printf 'Requesting a short-lived repository runner token through the existing Windows GitHub CLI session...\n'
  RUNNER_TOKEN="$(
    powershell.exe -NoProfile -NonInteractive -Command \
      "gh api --method POST repos/${REPO}/actions/runners/registration-token --jq .token" \
      | tr -d '\r\n'
  )"
  [[ -n "${RUNNER_TOKEN}" ]] || die "Could not obtain a repository runner registration token"

  ./config.sh \
    --unattended \
    --url "${REPO_URL}" \
    --token "${RUNNER_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABEL}" \
    --work "_work"

  RUNNER_TOKEN=""
  unset RUNNER_TOKEN
fi

if [[ "$(ps -p 1 -o comm= | tr -d ' ')" == "systemd" ]]; then
  if ! sudo ./svc.sh status >/dev/null 2>&1; then
    sudo ./svc.sh install "${USER}"
  fi
  sudo ./svc.sh start
  sudo ./svc.sh status
else
  if pgrep -f "${RUNNER_DIR}/bin/Runner.Listener" >/dev/null 2>&1; then
    printf 'Runner is already active.\n'
  else
    nohup ./run.sh > "${RUNNER_DIR}/runner.log" 2>&1 &
    runner_pid=$!
    disown "${runner_pid}" 2>/dev/null || true

    for _ in $(seq 1 30); do
      if grep -q "Listening for Jobs" "${RUNNER_DIR}/runner.log" 2>/dev/null; then
        printf 'Runner connected and listening for jobs.\n'
        exit 0
      fi
      if ! kill -0 "${runner_pid}" 2>/dev/null; then
        cat "${RUNNER_DIR}/runner.log" >&2 || true
        die "Runner exited before connecting"
      fi
      sleep 1
    done

    cat "${RUNNER_DIR}/runner.log" >&2 || true
    die "Runner did not reach the listening state"
  fi
fi

printf 'Dentora self-hosted runner setup complete.\n'
