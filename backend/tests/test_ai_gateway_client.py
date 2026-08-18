from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.core.license.service import (
    LicenseRejectedError,
    license_manager,
)
from app.core.llm.factory import get_provider
from app.core.llm.openai_provider import OpenAIProvider


class SettingsPatch:
    def __init__(self, **values):
        self.values = values
        self.original = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.original[key] = getattr(settings, key)
            setattr(settings, key, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.original.items():
            setattr(settings, key, value)


class AiGatewayConfigTests(unittest.TestCase):
    def test_gateway_url_derives_from_license_server(self):
        with SettingsPatch(
            AI_GATEWAY_BASE_URL="",
            LICENSE_SERVER_URL="https://license.example.test",
        ):
            self.assertEqual(
                settings.ai_gateway_base_url,
                "https://license.example.test/ai/v1/",
            )

    def test_explicit_gateway_url_wins(self):
        with SettingsPatch(
            AI_GATEWAY_BASE_URL=(
                "https://ai.example.test/custom/v1"
            ),
            LICENSE_SERVER_URL=(
                "https://license.example.test"
            ),
        ):
            self.assertEqual(
                settings.ai_gateway_base_url,
                "https://ai.example.test/custom/v1/",
            )


class AiGatewayCredentialTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_ai_disabled_blocks_gateway_credential(self):
        with SettingsPatch(
            LICENSE_ENFORCEMENT=True,
        ):
            with patch.object(
                license_manager,
                "get_status",
                AsyncMock(
                    return_value={
                        "active": True,
                        "features": [
                            "booking",
                            "core",
                        ],
                    }
                ),
            ):
                with self.assertRaises(
                    LicenseRejectedError
                ) as ctx:
                    await (
                        license_manager
                        .get_ai_gateway_credential()
                    )

        self.assertEqual(
            ctx.exception.status_code,
            403,
        )

    async def test_ai_enabled_returns_signed_lease(self):
        synthetic_token = (
            "synthetic-payload.synthetic-signature"
        )

        installation_id = (
            "installation-test-001"
        )

        fingerprint = (
            "fingerprint-test-001"
        )

        with SettingsPatch(
            LICENSE_ENFORCEMENT=True,
            LICENSE_MACHINE_FINGERPRINT=fingerprint,
        ):
            with (
                patch.object(
                    license_manager,
                    "get_status",
                    AsyncMock(
                        return_value={
                            "active": True,
                            "features": [
                                "ai",
                                "booking",
                                "core",
                            ],
                        }
                    ),
                ),
                patch.object(
                    license_manager,
                    "_load_state",
                    return_value={
                        "lease_token":
                            synthetic_token,
                    },
                ),
                patch.object(
                    license_manager,
                    "_verify_token",
                    return_value={
                        "product":
                            "dentalpin",
                        "v": 1,
                        "installation_id":
                            installation_id,
                        "fingerprint":
                            fingerprint,
                        "features": [
                            "ai",
                            "booking",
                            "core",
                        ],
                    },
                ),
                patch.object(
                    license_manager,
                    "installation_id",
                    return_value=
                        installation_id,
                ),
            ):
                result = await (
                    license_manager
                    .get_ai_gateway_credential()
                )

        self.assertEqual(
            result,
            synthetic_token,
        )


class AiGatewayProviderTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_provider_uses_dynamic_gateway_credential(
        self,
    ):
        captured = {}

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        async def resolver():
            return (
                "synthetic-payload."
                "synthetic-signature"
            )

        provider = OpenAIProvider(
            base_url=(
                "https://gateway.example.test/"
                "ai/v1/"
            ),
            api_key_resolver=resolver,
        )

        with patch(
            "openai.AsyncOpenAI",
            FakeAsyncOpenAI,
        ):
            await provider._client_for_request()

        self.assertEqual(
            captured["api_key"],
            (
                "synthetic-payload."
                "synthetic-signature"
            ),
        )

        self.assertEqual(
            captured["base_url"],
            (
                "https://gateway.example.test/"
                "ai/v1/"
            ),
        )

    async def test_licensed_factory_uses_gateway_not_openai_key(
        self,
    ):
        with SettingsPatch(
            LICENSE_ENFORCEMENT=True,
            LICENSE_SERVER_URL=(
                "https://license.example.test"
            ),
            AI_GATEWAY_BASE_URL="",
            OPENAI_API_KEY=(
                "must-not-be-used"
            ),
        ):
            provider = get_provider("openai")

            self.assertEqual(
                provider._api_key,
                "",
            )

            self.assertEqual(
                provider._base_url,
                (
                    "https://license.example.test/"
                    "ai/v1/"
                ),
            )

            self.assertIsNotNone(
                provider._api_key_resolver
            )

    async def test_development_mode_keeps_direct_provider(
        self,
    ):
        with SettingsPatch(
            LICENSE_ENFORCEMENT=False,
            OPENAI_API_KEY=(
                "development-test-key"
            ),
        ):
            provider = get_provider("openai")

            self.assertEqual(
                provider._api_key,
                "development-test-key",
            )

            self.assertIsNone(
                provider._base_url,
            )

            self.assertIsNone(
                provider._api_key_resolver,
            )


if __name__ == "__main__":
    unittest.main()
