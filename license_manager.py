
from __future__ import annotations

import json
import os
from pathlib import Path

from novel_writer.license import (
    LicenseError,
    LicenseInfo,
    current_machine_code,
    decode_activation_code,
    encode_activation_code,
    verify_local_license,
    verify_payload_for_machine,
)


LOCAL_LICENSE_DIR = Path(os.path.expanduser("~")) / ".dsbook"
LOCAL_LICENSE_PATH = LOCAL_LICENSE_DIR / "license.json"
LOCAL_LICENSE_STATE_PATH = LOCAL_LICENSE_DIR / "license_state.json"


def _license_state_path() -> Path:
    return LOCAL_LICENSE_PATH.with_name("license_state.json")


def get_machine_id() -> str:
    return current_machine_code()


def is_activated() -> bool:
    try:
        verify_local_license(
            LOCAL_LICENSE_PATH,
            expected_machine_code=current_machine_code(),
            usage_state_path=_license_state_path(),
        )
        return True
    except LicenseError:
        return False


def get_license_info() -> LicenseInfo | None:
    try:
        return verify_local_license(
            LOCAL_LICENSE_PATH,
            expected_machine_code=current_machine_code(),
            usage_state_path=_license_state_path(),
        )
    except LicenseError:
        return None


def verify_license_key(activation_code: str) -> bool:
    document = decode_activation_code(activation_code)
    if document is None:
        return False
    payload = document.get("payload")
    signature = document.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return False
    return verify_payload_for_machine(payload, signature)


def save_license(activation_code: str) -> Path:
    document = decode_activation_code(activation_code)
    if document is None:
        raise LicenseError("激活码格式错误，无法解析。")
    payload = document.get("payload")
    signature = document.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise LicenseError("激活码内容缺少 payload 或 signature。")
    if not verify_payload_for_machine(payload, signature):
        raise LicenseError("激活码无效或未绑定本机机器码。")
    LOCAL_LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_LICENSE_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_path = _license_state_path()
    if state_path.exists():
        state_path.unlink()
    return LOCAL_LICENSE_PATH


__all__ = [
    "LOCAL_LICENSE_PATH",
    "LOCAL_LICENSE_STATE_PATH",
    "encode_activation_code",
    "get_license_info",
    "get_machine_id",
    "is_activated",
    "save_license",
    "verify_license_key",
]
