
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import platform
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PRODUCT_ID = "deepseek-novel-writer"
LICENSE_FILE = "license.json"
PUBLIC_KEY_N = 24497957695562721989413714690755981671299318527683866442692369957598630478971296256830899315577991262198217056983103841500083432269508582495556764468605710879942789458765534660903883868987880984858737684646058337099877698485992313517077370715501103910126084242696173533948767574970596107168079842426855892429436959178985629516416619838975535816090204134160875489995981030459698829229909538640306001178411060500484942866332255890374589319900009048066743008092876183883702519283650734454861155648317171301502472718675097261310108014638768454906935324508233360218966888272161087319999800634846440659574698185647995304057
PUBLIC_KEY_E = 65537
SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class LicenseError(Exception):
    pass


@dataclass(frozen=True)
class LicenseInfo:
    customer: str
    license_type: str
    machine_code: str
    issued_at: str
    expires_at: str | None


def current_machine_code() -> str:
    raw = "|".join(_machine_fingerprint_parts())
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return "NW-" + "-".join(digest[index : index + 4] for index in range(0, 24, 4))


def verify_local_license(
    license_path: Path | None = None,
    *,
    expected_machine_code: str | None = None,
    usage_state_path: Path | None = None,
) -> LicenseInfo:
    path = license_path or Path(LICENSE_FILE)
    if not path.exists():
        raise LicenseError(f"未找到授权文件：{path}")

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise LicenseError("授权文件必须是 JSON 对象。")
    payload = document.get("payload")
    signature = document.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise LicenseError("授权文件格式错误，必须包含 payload 和 signature。")

    if not verify_signature(payload, signature):
        raise LicenseError("授权签名无效。")

    if payload.get("product") != PRODUCT_ID:
        raise LicenseError("授权文件不属于当前产品。")

    machine_code = str(payload.get("machine_code") or "")
    expected = expected_machine_code or current_machine_code()
    if machine_code != expected:
        raise LicenseError(
            f"授权文件绑定机器码 {machine_code}，当前机器码是 {expected}。"
        )

    expires_at = payload.get("expires_at")
    if not expires_at:
        raise LicenseError("授权文件缺少到期时间。")
    if expires_at:
        expiry = date.fromisoformat(str(expires_at))
        if date.today() > expiry:
            raise LicenseError(f"授权已过期：{expires_at}")

    _verify_and_update_usage_state(
        usage_state_path or path.with_name("license_state.json"),
        payload=payload,
        signature=signature,
        machine_code=machine_code,
    )

    return LicenseInfo(
        customer=str(payload.get("customer") or ""),
        license_type=str(payload.get("license_type") or "perpetual"),
        machine_code=machine_code,
        issued_at=str(payload.get("issued_at") or ""),
        expires_at=str(expires_at) if expires_at else None,
    )


def verify_signature(payload: dict[str, Any], signature: str) -> bool:
    signature_int = int.from_bytes(_b64decode(signature), "big")
    key_size = (PUBLIC_KEY_N.bit_length() + 7) // 8
    recovered = pow(signature_int, PUBLIC_KEY_E, PUBLIC_KEY_N).to_bytes(key_size, "big")
    expected = _encoded_digest(payload, key_size)
    return recovered == expected


def sign_payload(payload: dict[str, Any], private_key_d: int, private_key_n: int) -> str:
    key_size = (private_key_n.bit_length() + 7) // 8
    encoded = _encoded_digest(payload, key_size)
    signature_int = pow(int.from_bytes(encoded, "big"), private_key_d, private_key_n)
    return _b64encode(signature_int.to_bytes(key_size, "big"))


def build_license_payload(
    *,
    customer: str,
    machine_code: str,
    license_type: str = "perpetual",
    expires_at: str | None = None,
    duration_days: int | None = None,
) -> dict[str, Any]:
    if duration_days is not None:
        if duration_days < 1:
            raise LicenseError("授权天数必须大于 0。")
        expires_at = (date.today() + timedelta(days=duration_days)).isoformat()
        license_type = f"{duration_days}d"
    if not expires_at:
        raise LicenseError("必须提供授权到期日或授权天数。")
    return {
        "product": PRODUCT_ID,
        "customer": customer,
        "machine_code": machine_code,
        "license_type": license_type,
        "issued_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "expires_at": expires_at,
    }


def _encoded_digest(payload: dict[str, Any], key_size: int) -> bytes:
    digest = hashlib.sha256(_canonical_json(payload)).digest()
    digest_info = SHA256_DIGEST_INFO_PREFIX + digest
    padding_length = key_size - len(digest_info) - 3
    if padding_length < 8:
        raise LicenseError("RSA key is too short for SHA-256 signature.")
    return b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _machine_fingerprint_parts() -> list[str]:
    parts = [
        "product=" + PRODUCT_ID,
        "system=" + platform.system(),
        "machine=" + platform.machine(),
        "node=" + platform.node(),
        "computer=" + os.environ.get("COMPUTERNAME", ""),
        "processor=" + os.environ.get("PROCESSOR_IDENTIFIER", ""),
    ]
    guid = _windows_machine_guid()
    if guid:
        parts.append("machine_guid=" + guid)
    return parts


def _windows_machine_guid() -> str:
    if platform.system().lower() != "windows":
        return ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except OSError:
        return ""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)







def encode_activation_code(license_document: dict[str, Any]) -> str:
    payload = license_document.get("payload")
    signature = license_document.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise ValueError("license_document 必须包含 payload (dict) 和 signature (str)。")
    raw = json.dumps(license_document, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"DSBK1.{encoded}"


def decode_activation_code(code: str) -> dict[str, Any] | None:
    code = (code or "").strip()
    if not code:
        return None
    body = code.split(".", 1)[1] if code.startswith("DSBK1.") else code
    body = body.replace("\n", "").replace("\r", "").replace(" ", "")
    if not body:
        return None
    padding = "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(body + padding)
    except (binascii.Error, ValueError):
        return None
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    return document


def verify_payload_for_machine(
    payload: dict[str, Any],
    signature: str,
    *,
    machine_code: str | None = None,
) -> bool:
    if not verify_signature(payload, signature):
        return False
    if payload.get("product") != PRODUCT_ID:
        return False
    expected = machine_code or current_machine_code()
    if str(payload.get("machine_code") or "") != expected:
        return False
    expires_at = payload.get("expires_at")
    if not expires_at:
        return False
    try:
        expiry = date.fromisoformat(str(expires_at))
    except ValueError:
        return False
    if date.today() > expiry:
        return False
    return True


def _license_fingerprint(payload: dict[str, Any], signature: str) -> str:
    return hashlib.sha256(
        (_canonical_json(payload).decode("utf-8") + "." + signature).encode("utf-8")
    ).hexdigest()


def _usage_state_checksum(state: dict[str, Any]) -> str:
    payload = {key: value for key, value in state.items() if key != "checksum"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    material = f"{raw}|{PRODUCT_ID}|{current_machine_code()}|{PUBLIC_KEY_N}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _verify_and_update_usage_state(
    path: Path,
    *,
    payload: dict[str, Any],
    signature: str,
    machine_code: str,
) -> None:
    today = date.today().isoformat()
    fingerprint = _license_fingerprint(payload, signature)
    state: dict[str, Any] | None = None
    if path.exists():
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise LicenseError("授权使用记录格式错误。")
        checksum = str(parsed.get("checksum") or "")
        if checksum != _usage_state_checksum(parsed):
            raise LicenseError("授权使用记录被修改。")
        if parsed.get("license_fingerprint") != fingerprint:
            raise LicenseError("授权使用记录与当前授权不匹配。")
        if parsed.get("machine_code") != machine_code:
            raise LicenseError("授权使用记录与当前机器不匹配。")
        last_seen = str(parsed.get("last_seen") or "")
        if last_seen and today < last_seen:
            raise LicenseError("检测到系统时间回拨，授权已锁定。")
        state = parsed
    if state is None:
        state = {
            "machine_code": machine_code,
            "license_fingerprint": fingerprint,
            "first_seen": today,
            "last_seen": today,
            "checks": 0,
        }
    state["last_seen"] = today
    state["checks"] = int(state.get("checks") or 0) + 1
    state["checksum"] = _usage_state_checksum(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
