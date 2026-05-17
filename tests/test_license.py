
from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from novel_writer.license import (
    LicenseError,
    build_license_payload,
    current_machine_code,
    decode_activation_code,
    encode_activation_code,
    sign_payload,
    verify_local_license,
    verify_payload_for_machine,
)

import license_manager


PRIVATE_KEY_PATH = Path("seller_private_key.json")


def _load_private_key() -> dict[str, str] | None:
    if not PRIVATE_KEY_PATH.exists():
        return None
    parsed = json.loads(PRIVATE_KEY_PATH.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or "n" not in parsed or "d" not in parsed:
        return None
    return {"n": str(parsed["n"]), "d": str(parsed["d"])}


def _sign(machine_code: str, *, expires_at: str | None = None) -> dict:
    key = _load_private_key()
    if key is None:
        raise unittest.SkipTest("seller_private_key.json not available")
    if expires_at is None:
        expires_at = (date.today() + timedelta(days=30)).isoformat()
    payload = build_license_payload(
        customer="test",
        machine_code=machine_code,
        expires_at=expires_at,
    )
    signature = sign_payload(payload, int(key["d"]), int(key["n"]))
    return {"payload": payload, "signature": signature}


class MachineCodeTests(unittest.TestCase):
    def test_machine_code_has_public_format(self) -> None:
        self.assertRegex(current_machine_code(), r"^NW-[0-9A-F]{4}(-[0-9A-F]{4}){5}$")


class LicenseFileTests(unittest.TestCase):
    def test_signed_license_verifies_for_expected_machine(self) -> None:
        document = _sign("NW-1111-2222-3333-4444-5555-6666")
        with TemporaryDirectory() as temp_dir:
            license_path = Path(temp_dir) / "license.json"
            license_path.write_text(
                json.dumps(document, ensure_ascii=False),
                encoding="utf-8",
            )
            info = verify_local_license(
                license_path,
                expected_machine_code="NW-1111-2222-3333-4444-5555-6666",
                usage_state_path=Path(temp_dir) / "license_state.json",
            )
        self.assertEqual(info.customer, "test")

    def test_verify_local_license_rejects_wrong_machine(self) -> None:
        document = _sign("NW-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
        with TemporaryDirectory() as temp_dir:
            license_path = Path(temp_dir) / "license.json"
            license_path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(LicenseError):
                verify_local_license(
                    license_path,
                    expected_machine_code="NW-BBBB-BBBB-BBBB-BBBB-BBBB-BBBB",
                    usage_state_path=Path(temp_dir) / "license_state.json",
                )

    def test_verify_local_license_rejects_expired(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        document = _sign(
            "NW-1111-2222-3333-4444-5555-6666",
            expires_at=yesterday,
        )
        with TemporaryDirectory() as temp_dir:
            license_path = Path(temp_dir) / "license.json"
            license_path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(LicenseError):
                verify_local_license(
                    license_path,
                    expected_machine_code="NW-1111-2222-3333-4444-5555-6666",
                    usage_state_path=Path(temp_dir) / "license_state.json",
                )


class ActivationCodeTests(unittest.TestCase):
    def test_round_trip_encode_decode(self) -> None:
        document = _sign("NW-1111-2222-3333-4444-5555-6666")
        code = encode_activation_code(document)
        self.assertTrue(code.startswith("DSBK1."))
        decoded = decode_activation_code(code)
        self.assertEqual(decoded, document)

    def test_decode_accepts_raw_base64_without_prefix(self) -> None:
        document = _sign("NW-1111-2222-3333-4444-5555-6666")
        code = encode_activation_code(document)
        no_prefix = code.split(".", 1)[1]
        decoded = decode_activation_code(no_prefix)
        self.assertEqual(decoded, document)

    def test_decode_rejects_garbage(self) -> None:
        self.assertIsNone(decode_activation_code(""))
        self.assertIsNone(decode_activation_code("not-base64-!!!"))

    def test_verify_payload_for_machine_passes(self) -> None:
        document = _sign("NW-1111-2222-3333-4444-5555-6666")
        self.assertTrue(
            verify_payload_for_machine(
                document["payload"],
                document["signature"],
                machine_code="NW-1111-2222-3333-4444-5555-6666",
            )
        )

    def test_verify_payload_for_machine_rejects_other_machine(self) -> None:
        document = _sign("NW-1111-2222-3333-4444-5555-6666")
        self.assertFalse(
            verify_payload_for_machine(
                document["payload"],
                document["signature"],
                machine_code="NW-2222-3333-4444-5555-6666-7777",
            )
        )

    def test_build_license_payload_requires_time_limit(self) -> None:
        with self.assertRaises(LicenseError):
            build_license_payload(
                customer="test",
                machine_code="NW-1111-2222-3333-4444-5555-6666",
            )


class LicenseManagerTests(unittest.TestCase):
    def test_save_and_is_activated_round_trip(self) -> None:
        document = _sign(current_machine_code())
        code = encode_activation_code(document)
        with TemporaryDirectory() as temp_dir:
            license_path = Path(temp_dir) / "license.json"
            with mock.patch.object(license_manager, "LOCAL_LICENSE_PATH", license_path), \
                 mock.patch.object(license_manager, "LOCAL_LICENSE_DIR", license_path.parent):
                self.assertTrue(license_manager.verify_license_key(code))
                license_manager.save_license(code)
                self.assertTrue(license_manager.is_activated())
                info = license_manager.get_license_info()
                self.assertIsNotNone(info)
                self.assertEqual(info.customer, "test")

    def test_save_license_rejects_wrong_machine(self) -> None:
        document = _sign("NW-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF")
        code = encode_activation_code(document)
        with TemporaryDirectory() as temp_dir:
            license_path = Path(temp_dir) / "license.json"
            with mock.patch.object(license_manager, "LOCAL_LICENSE_PATH", license_path), \
                 mock.patch.object(license_manager, "LOCAL_LICENSE_DIR", license_path.parent):
                self.assertFalse(license_manager.verify_license_key(code))
                with self.assertRaises(LicenseError):
                    license_manager.save_license(code)


if __name__ == "__main__":
    unittest.main()
