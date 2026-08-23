"""Static contract tests for the Windows Mini PC / LAN / HTTPS deployment path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_client_compose_exposes_only_caddy_to_the_lan() -> None:
    compose = _read("docker-compose.client.yml")

    assert compose.count("\n    ports:\n") == 1
    assert '      - "80:80"' in compose
    assert '      - "443:443"' in compose

    for forbidden in ('"5432:5432"', '"8000:8000"', '"3000:3000"'):
        assert forbidden not in compose


def test_caddy_keeps_one_public_origin_for_frontend_and_api() -> None:
    caddyfile = _read("Caddyfile")

    assert "{$PUBLIC_URL:http://localhost}" in caddyfile
    assert "handle /api/*" in caddyfile
    assert "reverse_proxy backend:8000" in caddyfile
    assert "handle /health*" in caddyfile
    assert "reverse_proxy frontend:3000" in caddyfile


def test_first_start_remains_backward_compatible_until_lan_https_is_enabled() -> None:
    env_example = _read(".env.client.example")

    assert "PUBLIC_URL=http://localhost" in env_example
    assert "SETUP_LAN_HTTPS.bat <fixed-ip>" in env_example


def test_lan_https_setup_enforces_private_ip_firewall_and_trusted_tls() -> None:
    script = _read("SETUP_LAN_HTTPS.bat")

    assert "RFC1918" in script
    assert "WindowsBuiltInRole]::Administrator" in script
    assert "PUBLIC_URL=" in script
    assert "'https://' + $env:DENTORA_TARGET_IP" in script
    assert "-LocalPort 80" in script
    assert "-LocalPort 443" in script
    assert "-RemoteAddress LocalSubnet" in script
    assert "up -d --build" in script
    assert "caddy:/data/caddy/pki/authorities/local/root.crt" in script
    assert "dentora-lan-ca.crt" in script
    assert "certutil.exe -f -addstore Root" in script
    assert "$env:DENTORA_APP_URL + '/health'" in script

    assert "SkipCertificateCheck" not in script
    assert "ServicePointManager" not in script


def test_per_install_secrets_and_ca_export_cannot_be_committed_accidentally() -> None:
    gitignore = _read(".gitignore")

    assert ".env.client" in gitignore.splitlines()
    assert "dentora-lan-ca.crt" in gitignore.splitlines()


def test_install_doc_keeps_workstation_setup_out_of_this_stage() -> None:
    install_doc = _read("CLIENT_INSTALL_AR.md")

    assert "SETUP_LAN_HTTPS.bat 192.168.1.50" in install_doc
    assert "LocalSubnet" in install_doc
    assert "dentora-lan-ca.crt" in install_doc
    assert "Workstation Setup" in install_doc
    assert "هذه المرحلة تجهز السيرفر والـLAN/HTTPS فقط" in install_doc
