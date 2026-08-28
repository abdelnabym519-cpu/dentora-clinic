"""Static contract tests for the Windows workstation setup workflow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_workstation_kit_contains_only_public_connection_material() -> None:
    prepare = _read("PREPARE_WORKSTATION_KIT.bat")

    assert "Dentora_Workstation_Kit" in prepare
    assert "SETUP_DENTORA_WORKSTATION.bat" in prepare
    assert "dentora-lan-ca.crt" in prepare
    assert "dentora-workstation.conf" in prepare
    assert "DENTORA_URL=" in prepare
    assert "DENTORA_CA_SHA256=" in prepare
    assert "Get-FileHash -Algorithm SHA256" in prepare

    assert 'copy /y ".env.client"' not in prepare
    assert "POSTGRES_PASSWORD" not in prepare
    assert "LICENSE_PRIVATE" not in prepare


def test_workstation_kit_requires_https_private_ipv4_origin() -> None:
    prepare = _read("PREPARE_WORKSTATION_KIT.bat")

    assert "$uri.Scheme -ne 'https'" in prepare
    assert "IPAddress]::TryParse" in prepare
    assert "RFC1918" in prepare
    assert "port 443" in prepare
    assert "PUBLIC_URL" in prepare


def test_workstation_setup_validates_before_trusting_certificate() -> None:
    setup = _read("SETUP_DENTORA_WORKSTATION.bat")

    hash_check = setup.index("Get-FileHash -Algorithm SHA256")
    port_check = setup.index("Test-NetConnection")
    import_cert = setup.index("Import-Certificate")
    https_check = setup.index("Invoke-WebRequest")

    assert hash_check < port_check < import_cert < https_check
    assert "WindowsBuiltInRole]::Administrator" in setup
    assert "LocalMachine\\Root" in setup
    assert "DENTORA_CA_SHA256" in setup
    assert "Test-Path ('Cert:\\LocalMachine\\Root\\'" in setup


def test_workstation_setup_verifies_https_without_bypass() -> None:
    setup = _read("SETUP_DENTORA_WORKSTATION.bat")

    assert "Test-NetConnection" in setup
    assert "-Port 443" in setup
    assert "'/health'" in setup
    assert "Invoke-WebRequest" in setup
    assert "SkipCertificateCheck" not in setup
    assert "ServerCertificateValidationCallback" not in setup
    assert "ServicePointManager" not in setup


def test_workstation_setup_creates_shared_shortcut_and_needs_no_docker() -> None:
    setup = _read("SETUP_DENTORA_WORKSTATION.bat")

    assert "$env:PUBLIC" in setup
    assert "Dentora Clinic.url" in setup
    assert "Docker" in setup
    assert "where docker" not in setup
    assert "docker compose" not in setup


def test_workstation_documentation_preserves_scope_boundary() -> None:
    guide = _read("WORKSTATION_SETUP_AR.md")
    install_doc = _read("CLIENT_INSTALL_AR.md")

    assert "PREPARE_WORKSTATION_KIT.bat" in guide
    assert "SETUP_DENTORA_WORKSTATION.bat" in guide
    assert "بدون أي certificate bypass" in guide
    assert "لا تنفذ Backup / Restore" in guide
    assert "PREPARE_WORKSTATION_KIT.bat" in install_doc
    assert "SETUP_DENTORA_WORKSTATION.bat" in install_doc
