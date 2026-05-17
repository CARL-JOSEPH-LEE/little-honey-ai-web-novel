from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from novel_writer.license import build_license_payload, encode_activation_code, sign_payload


FONT = "Microsoft YaHei UI"
MACHINE_CODE_PATTERN = re.compile(r"^NW(-[0-9A-F]{4}){6}$")


def _resource_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / name


def _load_private_key() -> dict[str, str]:
    candidates = [
        Path.cwd() / "seller_private_key.json",
        _resource_path("seller_private_key.json"),
    ]
    for path in candidates:
        if path.exists():
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and "n" in parsed and "d" in parsed:
                return {"n": str(parsed["n"]), "d": str(parsed["d"])}
    raise RuntimeError("找不到签发私钥。")


def _normalize_machine_code(value: str) -> str:
    text = value.strip().upper()
    text = text.replace(" ", "").replace("—", "-").replace("－", "-")
    return text


def generate_activation_code(machine_code: str, days: int) -> tuple[str, str, Path]:
    machine_code = _normalize_machine_code(machine_code)
    if not MACHINE_CODE_PATTERN.match(machine_code):
        raise ValueError("机器码格式不对。请粘贴 NW-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX 这种格式。")
    if days < 1:
        raise ValueError("授权天数必须大于 0。")
    key = _load_private_key()
    payload = build_license_payload(
        customer=f"{days}天授权",
        machine_code=machine_code,
        duration_days=days,
    )
    signature = sign_payload(payload, int(key["d"]), int(key["n"]))
    code = encode_activation_code({"payload": payload, "signature": signature})
    output_dir = Path.cwd() / "activation-codes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{machine_code}-{days}d-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    output_path.write_text(code + "\n", encoding="utf-8")
    return code, str(payload["expires_at"]), output_path


class LicenseIssuerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("小蜜AI授权码生成器")
        self.geometry("820x620")
        self.minsize(760, 560)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self._build()

    def _build(self) -> None:
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=26, pady=22)

        ctk.CTkLabel(
            root,
            text="小蜜AI授权码生成器",
            font=ctk.CTkFont(family=FONT, size=26, weight="bold"),
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(
            root,
            text="粘贴客户机器码，填写授权天数，点击生成。生成后会自动复制，并保存到 activation-codes 文件夹。",
            font=ctk.CTkFont(family=FONT, size=13),
            text_color="gray65",
            wraplength=740,
            justify="left",
        ).pack(anchor="w", pady=(0, 22))

        ctk.CTkLabel(
            root,
            text="客户机器码",
            font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
        ).pack(anchor="w")
        self.machine_entry = ctk.CTkEntry(
            root,
            height=42,
            font=ctk.CTkFont(family="Consolas", size=14),
            placeholder_text="NW-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX",
        )
        self.machine_entry.pack(fill="x", pady=(6, 16))

        row = ctk.CTkFrame(root, fg_color="transparent")
        row.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(
            row,
            text="授权天数",
            font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
        ).pack(side="left", padx=(0, 12))
        self.days_entry = ctk.CTkEntry(
            row,
            width=120,
            height=38,
            font=ctk.CTkFont(family="Consolas", size=14),
        )
        self.days_entry.insert(0, "30")
        self.days_entry.pack(side="left")
        for days in [7, 30, 90, 180, 365, 9999]:
            ctk.CTkButton(
                row,
                text=str(days),
                width=64,
                height=34,
                fg_color=("gray70", "gray30"),
                hover_color=("gray60", "gray35"),
                command=lambda value=days: self._set_days(value),
            ).pack(side="left", padx=(8, 0))

        button_row = ctk.CTkFrame(root, fg_color="transparent")
        button_row.pack(fill="x", pady=(0, 14))
        ctk.CTkButton(
            button_row,
            text="生成并复制激活码",
            width=220,
            height=46,
            font=ctk.CTkFont(family=FONT, size=16, weight="bold"),
            command=self._generate,
        ).pack(side="left")
        ctk.CTkButton(
            button_row,
            text="清空",
            width=100,
            height=46,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray35"),
            command=self._clear,
        ).pack(side="left", padx=10)

        self.status_label = ctk.CTkLabel(
            root,
            text="等待生成",
            font=ctk.CTkFont(family=FONT, size=13),
            text_color="gray65",
            anchor="w",
        )
        self.status_label.pack(fill="x", pady=(0, 8))

        self.output_box = ctk.CTkTextbox(
            root,
            height=260,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="char",
        )
        self.output_box.pack(fill="both", expand=True)

    def _set_days(self, days: int) -> None:
        self.days_entry.delete(0, "end")
        self.days_entry.insert(0, str(days))

    def _clear(self) -> None:
        self.machine_entry.delete(0, "end")
        self.output_box.delete("1.0", "end")
        self.status_label.configure(text="等待生成", text_color="gray65")

    def _generate(self) -> None:
        try:
            days = int(self.days_entry.get().strip())
            code, expires_at, output_path = generate_activation_code(
                self.machine_entry.get(),
                days,
            )
        except Exception as exc:
            self.status_label.configure(text=f"生成失败：{exc}", text_color=("#E74C3C", "#C0392B"))
            messagebox.showerror("生成失败", str(exc))
            return
        self.output_box.delete("1.0", "end")
        self.output_box.insert("1.0", code)
        self.clipboard_clear()
        self.clipboard_append(code)
        self.status_label.configure(
            text=f"已生成，授权到期：{expires_at}，已复制，已保存：{output_path}",
            text_color=("#2ECC71", "#27AE60"),
        )
        messagebox.showinfo("成功", "激活码已生成并复制。")


def main() -> None:
    app = LicenseIssuerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
