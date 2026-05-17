
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .license import (
    build_license_payload,
    encode_activation_code,
    sign_payload,
)


PRIVATE_KEY_FILE = Path("seller_private_key.json")

MACHINE_CODE_PATTERN = re.compile(r"^NW(-[0-9A-F]{4}){6}$")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="license-admin")
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser(
        "issue-activation-code",
        help="基于客户机器码签发激活码字符串（推荐）。",
    )
    issue.add_argument("machine_code", nargs="?", help="客户机器码")
    issue.add_argument("days", nargs="?", type=int, help="授权天数，单位：天")
    issue.add_argument(
        "--output-dir", type=Path, default=Path("activation-codes"),
        help="额外保存到该目录下一份 .txt 备份。",
    )
    issue.add_argument(
        "--private-key", type=Path, default=PRIVATE_KEY_FILE,
        help="私钥路径，默认 seller_private_key.json。",
    )

    args = parser.parse_args(argv)
    if args.command == "issue-activation-code":
        issue_activation_code(args)
        return


def issue_activation_code(args: argparse.Namespace) -> None:
    if not args.private_key.exists():
        raise SystemExit(
            f"[错误] 找不到私钥 {args.private_key}\n"
            "        请把 seller_private_key.json 放在当前目录。"
        )

    machine_code = (args.machine_code or "").strip()
    if not machine_code:
        print(
            "请输入客户发给你的机器码 "
            "(格式: NW-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX)"
        )
        machine_code = _prompt("> ")
    machine_code = machine_code.strip().upper()
    if not MACHINE_CODE_PATTERN.match(machine_code):
        raise SystemExit(
            "[错误] 机器码格式错误\n"
            "        应为 NW- 后跟 6 段 4 位 16 进制\n"
            "        例：NW-EC2B-4597-56D3-CBC2-42F3-2836"
        )

    days = args.days
    if days is None:
        print("请输入授权天数（单位：天，例如 30 / 365 / 9999）")
        raw_days = _prompt("> ")
        try:
            days = int(raw_days)
        except ValueError:
            raise SystemExit("[错误] 授权天数必须是整数。") from None
    if days < 1:
        raise SystemExit("[错误] 授权天数必须大于 0。")

    key = read_private_key(args.private_key)
    payload = build_license_payload(
        customer=f"{days}天授权",
        machine_code=machine_code,
        duration_days=days,
    )
    signature = sign_payload(
        payload,
        private_key_d=int(key["d"]),
        private_key_n=int(key["n"]),
    )
    document = {"payload": payload, "signature": signature}
    activation_code = encode_activation_code(document)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{machine_code}-{timestamp}.txt"
    output_path.write_text(activation_code + "\n", encoding="utf-8")

    print()
    print("============================================")
    print(f"  激活码已生成 ({days} 天)")
    print("============================================")
    print(f"  机器码     : {machine_code}")
    print(f"  到期日期   : {payload['expires_at']}")
    print(f"  备份文件   : {output_path}")
    print()
    print("  激活码 (整行复制发给客户)：")
    print()
    print(activation_code)
    print()
    print("  使用方式：")
    print("    1. 客户打开 小蜜AI网文.exe")
    print("    2. 进入『设置』页面，粘贴上面整段激活码")
    print("    3. 点『激活授权』即可")
    print("============================================")
def read_private_key(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(
            f"私钥文件不存在：{path}。请保管好 seller_private_key.json，绝不外发。"
        )
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or "n" not in parsed or "d" not in parsed:
        raise RuntimeError("私钥文件格式错误：必须包含 n 和 d。")
    return {"n": str(parsed["n"]), "d": str(parsed["d"])}


def _prompt(message: str) -> str:
    sys.stdout.write(message)
    sys.stdout.flush()
    line = sys.stdin.readline()
    return line.strip() if line else ""


if __name__ == "__main__":
    main()
