
from __future__ import annotations

import base64
import ctypes
import json
import os
import queue
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from license_manager import (
    LOCAL_LICENSE_PATH,
    get_license_info,
    get_machine_id,
    is_activated,
    save_license,
    verify_license_key,
)
from novel_engine import NovelEngine
from novel_project import DEFAULT_PROJECTS_DIR, NovelProject
from novel_writer.config import (
    DEFAULT_INPUT_TOKEN_LIMIT,
    DEFAULT_OUTPUT_TOKEN_LIMIT,
    INPUT_TOKEN_SAFETY_MARGIN,
)






MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]
REASONING_EFFORTS = ["high", "max"]

FONT = "Microsoft YaHei UI"
SETTINGS_DIR = Path(os.path.expanduser("~")) / ".dsbook"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"
PROJECTS_DIR = DEFAULT_PROJECTS_DIR
DEFAULT_SETTINGS = {
    "api_key": "",
    "model": "deepseek-v4-flash",
    "reasoning_effort": "high",
    "thinking_enabled": True,
}


def _should_follow_progress_scroll(yview: tuple[float, float], threshold: float = 0.02) -> bool:
    if len(yview) < 2:
        return True
    return yview[1] >= 1.0 - threshold


def _frozen_root() -> Path:

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _bootstrap_app_dirs() -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _seed_api_key_from_disk() -> str:

    api_txt = _frozen_root() / "API.txt"
    if api_txt.exists():
        text = api_txt.read_text(encoding="utf-8").strip()
        if text:
            return text
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    return env_key


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _protect_secret(value: str) -> str:
    if not value:
        return ""
    if not sys.platform.startswith("win"):
        return value
    raw = value.encode("utf-8")
    in_blob = _DataBlob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError("API Key 加密失败。")
    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _unprotect_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith("dpapi:") or not sys.platform.startswith("win"):
        return value
    raw = base64.b64decode(value.split(":", 1)[1])
    in_blob = _DataBlob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError("API Key 解密失败。")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)







class NovelWriterApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("小蜜AI网文")
        self.geometry("1400x900")
        self.minsize(1180, 760)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        _bootstrap_app_dirs()

        self.settings = self._load_settings()
        self.project: NovelProject | None = None
        self.engine: NovelEngine | None = None
        self.writing_thread: threading.Thread | None = None
        self._chunk_queue: queue.Queue[str] = queue.Queue()
        self._writing_start_time: float = 0.0
        self._chapter_text_chars: int = 0
        self._lib_project: NovelProject | None = None
        self._build_sidebar()
        self._build_content_area()
        self._build_settings_page()
        self._build_create_page()
        self._build_progress_page()
        self._build_library_page()
        self._poll_chunk_queue()
        self._tick_elapsed()
        self._refresh_license_status()

        self.show_page("settings")





    def _load_settings(self) -> dict:
        if SETTINGS_PATH.exists():
            try:
                with SETTINGS_PATH.open("r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        merged = dict(DEFAULT_SETTINGS)
                        merged.update(data)
                        if not merged.get("api_key") and merged.get("api_key_protected"):
                            merged["api_key"] = _unprotect_secret(str(merged["api_key_protected"]))
                        return merged
            except (OSError, json.JSONDecodeError):
                pass
        seeded = dict(DEFAULT_SETTINGS)
        seeded["api_key"] = _seed_api_key_from_disk()
        return seeded

    def _save_settings(self) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = dict(self.settings)
        key = str(data.get("api_key") or "")
        if key:
            data["api_key_protected"] = _protect_secret(key)
            data["api_key"] = ""
        with SETTINGS_PATH.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)





    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, width=220, corner_radius=0,
                          fg_color=("gray85", "gray17"))
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        ctk.CTkLabel(
            sb,
            text="小蜜AI网文",
            font=ctk.CTkFont(family=FONT, size=22, weight="bold"),
        ).pack(pady=(28, 4))
        ctk.CTkLabel(
            sb,
            text="AI 长篇网文写作工具",
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray50",
        ).pack(pady=(0, 26))

        self.nav_btns: dict[str, ctk.CTkButton] = {}
        for pid, label in [
            ("settings", "⚙  设    置"),
            ("create", "✦  新建小说"),
            ("progress", "✎  写作进度"),
            ("library", "☰  作 品 库"),
        ]:
            btn = ctk.CTkButton(
                sb, text=label,
                font=ctk.CTkFont(family=FONT, size=14),
                height=46, corner_radius=8,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray25"),
                anchor="w",
                command=lambda p=pid: self.show_page(p),
            )
            btn.pack(pady=3, padx=15, fill="x")
            self.nav_btns[pid] = btn

        ctk.CTkFrame(sb, height=2, fg_color="gray40").pack(fill="x", padx=15, pady=(20, 14))

        ctk.CTkButton(
            sb,
            text="打开项目目录",
            font=ctk.CTkFont(family=FONT, size=12),
            height=34,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray35"),
            command=self._open_projects_root,
        ).pack(padx=15, pady=(0, 6), fill="x")

        ctk.CTkButton(
            sb,
            text="打开 DeepSeek 平台",
            font=ctk.CTkFont(family=FONT, size=12),
            height=34,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray35"),
            command=lambda: webbrowser.open("https://platform.deepseek.com"),
        ).pack(padx=15, pady=(0, 6), fill="x")





    def _build_content_area(self) -> None:
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.pack(side="right", fill="both", expand=True)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.pages: dict[str, ctk.CTkFrame] = {}

    def show_page(self, name: str) -> None:
        for pid, btn in self.nav_btns.items():
            btn.configure(
                fg_color=("#3B8ED0", "#1F6AA5") if pid == name else "transparent"
            )
        for page in self.pages.values():
            page.grid_remove()
        self.pages[name].grid(row=0, column=0, sticky="nsew")





    def _build_settings_page(self) -> None:
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["settings"] = page

        inner = ctk.CTkFrame(page, fg_color="transparent")
        inner.pack(padx=40, pady=24, anchor="n", fill="x")

        ctk.CTkLabel(
            inner,
            text="系统设置",
            font=ctk.CTkFont(family=FONT, size=26, weight="bold"),
        ).pack(anchor="w", pady=(0, 22))


        ctk.CTkButton(
            inner,
            text="DeepSeek API 密钥（点击打开平台）",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
            fg_color="transparent",
            hover_color=("gray80", "gray25"),
            text_color=("#1F6AA5", "#6BB6FF"),
            anchor="w",
            command=lambda: webbrowser.open("https://platform.deepseek.com"),
        ).pack(anchor="w")
        self.api_key_entry = ctk.CTkEntry(
            inner, width=620, height=40,
            font=ctk.CTkFont(family=FONT, size=13),
            placeholder_text="sk-...",
            show="*",
        )
        self.api_key_entry.pack(anchor="w", pady=(4, 2), fill="x")
        if self.settings.get("api_key"):
            self.api_key_entry.insert(0, self.settings["api_key"])
        ctk.CTkLabel(
            inner,
            text=(
                "不知道怎么弄就按这几步：1. 点击上面的蓝色标题打开 DeepSeek 平台；"
                "2. 用手机号或邮箱注册并登录；3. 进入左侧 API keys / API 密钥 页面；"
                "4. 点击创建 API Key，把生成的 sk- 开头字符串复制回来；"
                "5. 粘贴到上面的输入框，点保存密钥。不要把 API Key 发给别人。"
            ),
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
            wraplength=620, justify="left",
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkButton(
            inner, text="保存密钥", width=200, height=36,
            font=ctk.CTkFont(family=FONT, size=13),
            command=self._save_api_key,
        ).pack(anchor="w", pady=(2, 22))


        ctk.CTkLabel(
            inner,
            text="模型与推理设置",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        ).pack(anchor="w", pady=(4, 4))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(anchor="w", fill="x")

        ctk.CTkLabel(
            row, text="模型：",
            font=ctk.CTkFont(family=FONT, size=13),
        ).pack(side="left", padx=(0, 6))
        self.model_var = ctk.StringVar(
            value=self.settings.get("model", DEFAULT_SETTINGS["model"])
        )
        ctk.CTkOptionMenu(
            row, width=200, height=34,
            values=MODELS,
            variable=self.model_var,
            font=ctk.CTkFont(family=FONT, size=12),
            command=self._on_model_change,
        ).pack(side="left", padx=(0, 18))

        ctk.CTkLabel(
            row, text="推理强度：",
            font=ctk.CTkFont(family=FONT, size=13),
        ).pack(side="left", padx=(0, 6))
        self.reasoning_var = ctk.StringVar(
            value=self.settings.get("reasoning_effort", DEFAULT_SETTINGS["reasoning_effort"])
        )
        ctk.CTkOptionMenu(
            row, width=140, height=34,
            values=REASONING_EFFORTS,
            variable=self.reasoning_var,
            font=ctk.CTkFont(family=FONT, size=12),
            command=self._on_reasoning_change,
        ).pack(side="left", padx=(0, 18))

        self.thinking_var = ctk.BooleanVar(
            value=bool(self.settings.get("thinking_enabled", True))
        )
        ctk.CTkSwitch(
            row, text="思考模式",
            variable=self.thinking_var,
            font=ctk.CTkFont(family=FONT, size=12),
            command=self._on_thinking_change,
        ).pack(side="left", padx=(0, 18))

        ctk.CTkLabel(
            inner,
            text=(
                "推荐：deepseek-v4-flash + 推理强度 high + 思考模式开。"
                "max 思考更稳但更慢更贵；如果你追求顶级爆款可调到 max。"
            ),
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
            wraplength=620, justify="left",
        ).pack(anchor="w", pady=(6, 18))

        sep = ctk.CTkFrame(inner, height=2, fg_color="gray40")
        sep.pack(fill="x", pady=12)


        ctk.CTkLabel(
            inner,
            text="软件授权",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        ).pack(anchor="w", pady=(2, 6))

        mid = get_machine_id()
        machine_row = ctk.CTkFrame(inner, fg_color="transparent")
        machine_row.pack(anchor="w", fill="x")
        ctk.CTkLabel(
            machine_row, text="本机机器码：",
            font=ctk.CTkFont(family=FONT, size=13),
        ).pack(side="left")
        self.machine_entry = ctk.CTkEntry(
            machine_row, width=320, height=34,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.machine_entry.insert(0, mid)
        self.machine_entry.configure(state="readonly")
        self.machine_entry.pack(side="left", padx=8)
        ctk.CTkButton(
            machine_row, text="复制", width=80, height=34,
            font=ctk.CTkFont(family=FONT, size=12),
            command=self._copy_machine_code,
        ).pack(side="left", padx=4)
        ctk.CTkLabel(
            inner,
            text=(
                "把上面这串机器码发给卖家。卖家会用它生成只属于你这台电脑的"
                "限时激活码。激活后只能在这台电脑和授权时间内使用，不能用于其他电脑。"
            ),
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
            wraplength=620, justify="left",
        ).pack(anchor="w", pady=(8, 6))

        ctk.CTkLabel(
            inner, text="激活码（卖家发给你的字符串）",
            font=ctk.CTkFont(family=FONT, size=13),
        ).pack(anchor="w", pady=(8, 2))
        self.license_entry = ctk.CTkTextbox(
            inner, width=620, height=110,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="char",
        )
        self.license_entry.pack(anchor="w", fill="x")
        ctk.CTkLabel(
            inner,
            text="支持 DSBK1.xxxxx 形式或纯 base64；粘贴后点下方按钮激活。",
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
        ).pack(anchor="w")
        ctk.CTkButton(
            inner, text="激活授权", width=200, height=36,
            font=ctk.CTkFont(family=FONT, size=13),
            command=self._activate_license,
        ).pack(anchor="w", pady=(8, 6))

        self.license_status = ctk.CTkLabel(
            inner, text="正在检查授权…",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        )
        self.license_status.pack(anchor="w", pady=(0, 8))

    def _save_api_key(self) -> None:
        key = self.api_key_entry.get().strip()
        if not key:
            messagebox.showwarning("提示", "请输入 API 密钥")
            return
        self.settings["api_key"] = key
        self._save_settings()
        messagebox.showinfo("成功", "API 密钥已保存到 ~/.dsbook/settings.json")

    def _on_model_change(self, value: str) -> None:
        self.settings["model"] = value
        self._save_settings()

    def _on_reasoning_change(self, value: str) -> None:
        self.settings["reasoning_effort"] = value
        self._save_settings()

    def _on_thinking_change(self) -> None:
        self.settings["thinking_enabled"] = bool(self.thinking_var.get())
        self._save_settings()

    def _copy_machine_code(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.machine_entry.get())
        messagebox.showinfo("已复制", "机器码已复制到剪贴板，可以发给卖家了。")

    def _activate_license(self) -> None:
        code = self.license_entry.get("0.0", "end").strip()
        if not code:
            messagebox.showwarning("提示", "请粘贴激活码")
            return
        if not verify_license_key(code):
            messagebox.showerror("失败", "激活码无效，或者不属于这台电脑。")
            self._refresh_license_status()
            return
        try:
            save_license(code)
        except Exception as exc:
            messagebox.showerror("失败", f"保存授权失败：{exc}")
            return
        messagebox.showinfo("成功", "授权激活成功，欢迎使用！")
        self.license_entry.delete("0.0", "end")
        self._refresh_license_status()

    def _refresh_license_status(self) -> None:
        info = get_license_info()
        if info is None:
            self.license_status.configure(
                text="✗ 未激活，必须激活后才能开始写作",
                text_color=("#E74C3C", "#C0392B"),
            )
        else:
            extra = f"，到期 {info.expires_at}" if info.expires_at else ""
            self.license_status.configure(
                text=f"✓ 已激活：{info.customer}{extra}",
                text_color=("#2ECC71", "#27AE60"),
            )





    def _build_create_page(self) -> None:
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.pages["create"] = page

        ctk.CTkLabel(
            page, text="【作品标题】（可不填，不填则由 AI 在初始对话时生成）",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        ).pack(anchor="w", padx=30, pady=(20, 4))
        self.title_entry = ctk.CTkEntry(
            page, height=38,
            font=ctk.CTkFont(family=FONT, size=13),
            placeholder_text="例如：借命天书",
        )
        self.title_entry.pack(anchor="w", padx=30, fill="x")

        ctk.CTkLabel(
            page, text="【目标读者】（必选）",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        ).pack(anchor="w", padx=30, pady=(14, 4))
        self.audience_var = ctk.StringVar(value="男频")
        ctk.CTkSegmentedButton(
            page,
            values=["男频", "女频"],
            variable=self.audience_var,
            height=38,
            font=ctk.CTkFont(family=FONT, size=13),
        ).pack(anchor="w", padx=30)

        ctk.CTkLabel(
            page, text="【作品标签】（完全由你自己输入，用逗号、顿号、空格或换行分隔）",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        ).pack(anchor="w", padx=30, pady=(14, 4))
        self.custom_tags_entry = ctk.CTkEntry(
            page, height=38,
            font=ctk.CTkFont(family=FONT, size=13),
            placeholder_text="例如：玄幻、群像、智斗、废土修仙、无系统、克苏鲁",
        )
        self.custom_tags_entry.pack(anchor="w", padx=30, fill="x")

        ctk.CTkLabel(
            page, text="【作品简介】（可不填，不填则由 AI 在初始对话时生成，建议 500 字以内）",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        ).pack(anchor="w", padx=30, pady=(14, 4))
        self.synopsis_input = ctk.CTkTextbox(
            page,
            height=120,
            font=ctk.CTkFont(family=FONT, size=13),
            wrap="word",
        )
        self.synopsis_input.pack(anchor="w", padx=30, fill="x")

        ctk.CTkFrame(page, height=2, fg_color="gray40").pack(
            fill="x", padx=30, pady=14)


        chap_frame = ctk.CTkFrame(page, fg_color="transparent")
        chap_frame.pack(anchor="w", padx=30, pady=(2, 4), fill="x")
        ctk.CTkLabel(
            chap_frame, text="目标章数：",
            font=ctk.CTkFont(family=FONT, size=14),
        ).pack(side="left", padx=(0, 10))
        self.chapter_count_var = ctk.IntVar(value=1000)
        self.chapter_slider = ctk.CTkSlider(
            chap_frame, from_=50, to=10000, width=420,
            number_of_steps=199,
            variable=self.chapter_count_var,
            command=self._on_chapter_slider,
        )
        self.chapter_slider.pack(side="left")
        self.chapter_label = ctk.CTkLabel(
            chap_frame, text="1000 章 ≈ 500 万字",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
            width=180,
        )
        self.chapter_label.pack(side="left", padx=10)


        word_frame = ctk.CTkFrame(page, fg_color="transparent")
        word_frame.pack(anchor="w", padx=30, pady=(8, 4), fill="x")
        ctk.CTkLabel(
            word_frame, text="每章字数：",
            font=ctk.CTkFont(family=FONT, size=14),
        ).pack(side="left", padx=(0, 10))
        self.words_per_chapter_var = ctk.IntVar(value=5000)
        self.words_slider = ctk.CTkSlider(
            word_frame, from_=1000, to=20000, width=420,
            number_of_steps=38,
            variable=self.words_per_chapter_var,
            command=self._on_words_slider,
        )
        self.words_slider.pack(side="left")
        self.words_label = ctk.CTkLabel(
            word_frame, text="5000 字 / 章",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
            width=180,
        )
        self.words_label.pack(side="left", padx=10)


        token_frame = ctk.CTkFrame(page, fg_color=("gray90", "gray18"), corner_radius=10)
        token_frame.pack(anchor="w", padx=30, pady=(14, 4), fill="x")
        ctk.CTkLabel(
            token_frame, text="Token 限制",
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(10, 6))

        token_row = ctk.CTkFrame(token_frame, fg_color="transparent")
        token_row.pack(padx=14, pady=(0, 8), anchor="w", fill="x")

        ctk.CTkLabel(
            token_row, text="输入token限制：",
            font=ctk.CTkFont(family=FONT, size=12),
        ).pack(side="left")
        self.input_token_limit_var = ctk.StringVar(value=str(DEFAULT_INPUT_TOKEN_LIMIT))
        self.input_token_entry = ctk.CTkEntry(
            token_row, width=120, height=30,
            textvariable=self.input_token_limit_var,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.input_token_entry.pack(side="left", padx=(4, 18))

        ctk.CTkLabel(
            token_row, text="输出token限制：",
            font=ctk.CTkFont(family=FONT, size=12),
        ).pack(side="left")
        self.output_token_limit_var = ctk.StringVar(value=str(DEFAULT_OUTPUT_TOKEN_LIMIT))
        self.output_token_entry = ctk.CTkEntry(
            token_row, width=120, height=30,
            textvariable=self.output_token_limit_var,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.output_token_entry.pack(side="left", padx=(4, 18))

        ctk.CTkLabel(
            token_frame,
            text=(
                "输入token限制：每次写作时最多参考多少上文、设定、摘要和本章方向。"
                "输出token限制：模型一次最多生成多少内容。"
                "两者合计最好不要超过 1M。默认 800000 + 200000。"
            ),
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
            wraplength=900, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 10))


        quality_frame = ctk.CTkFrame(page, fg_color=("gray90", "gray18"), corner_radius=10)
        quality_frame.pack(anchor="w", padx=30, pady=(14, 4), fill="x")
        ctk.CTkLabel(
            quality_frame, text="质量参数（评审会循环到达标）",
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(10, 6))

        q_row = ctk.CTkFrame(quality_frame, fg_color="transparent")
        q_row.pack(padx=14, pady=(0, 10), anchor="w", fill="x")

        ctk.CTkLabel(
            q_row, text="目标质量分：",
            font=ctk.CTkFont(family=FONT, size=12),
        ).pack(side="left")
        self.min_quality_score_var = ctk.IntVar(value=88)
        ctk.CTkOptionMenu(
            q_row, width=70, height=30,
            values=["70", "75", "80", "82", "85", "88", "90", "92", "95", "98"],
            variable=ctk.StringVar(value=str(self.min_quality_score_var.get())),
            font=ctk.CTkFont(family=FONT, size=12),
            command=lambda v: self.min_quality_score_var.set(int(v)),
        ).pack(side="left", padx=(4, 0))

        ctk.CTkLabel(
            quality_frame,
            text=(
                "推荐：88 分门槛。低于目标分或存在致命问题时，软件会按评审意见"
                "重写并再次评审，直到达标；黄金三章会自动用 90 分兜底。"
            ),
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
            wraplength=900, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 10))

        flow_frame = ctk.CTkFrame(page, fg_color=("gray90", "gray18"), corner_radius=10)
        flow_frame.pack(anchor="w", padx=30, pady=(14, 4), fill="x")
        ctk.CTkLabel(
            flow_frame, text="章节推进方式",
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(10, 6))
        self.ask_each_chapter_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            flow_frame,
            text="每章结束后询问我下一章怎么写",
            variable=self.ask_each_chapter_var,
            onvalue=True,
            offvalue=False,
            font=ctk.CTkFont(family=FONT, size=13),
        ).pack(anchor="w", padx=14, pady=(0, 6))
        ctk.CTkLabel(
            flow_frame,
            text="勾选后，软件每完成一章都会弹出输入框；不勾选则全自动连续写下去。",
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
            wraplength=900, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 10))

        ctk.CTkButton(
            page,
            text="▶  开 始 创 作",
            width=380, height=58,
            corner_radius=12,
            font=ctk.CTkFont(family=FONT, size=18, weight="bold"),
            command=self._start_writing,
        ).pack(pady=24)

    def _on_chapter_slider(self, value: float) -> None:
        chapters = int(value)
        self.chapter_count_var.set(chapters)
        words = self.words_per_chapter_var.get()
        total = chapters * words / 10000
        self.chapter_label.configure(text=f"{chapters} 章 ≈ {total:.0f} 万字")

    def _on_words_slider(self, value: float) -> None:
        words = int(round(value / 500) * 500)
        self.words_per_chapter_var.set(words)
        self.words_label.configure(text=f"{words} 字 / 章")
        chapters = self.chapter_count_var.get()
        total = chapters * words / 10000
        self.chapter_label.configure(text=f"{chapters} 章 ≈ {total:.0f} 万字")

    @staticmethod
    def _parse_token_limit(value: str, label: str) -> int:
        normalized = value.strip().replace(",", "")
        if not normalized.isdigit():
            raise ValueError(f"{label}必须是正整数。")
        parsed = int(normalized)
        if parsed <= 0:
            raise ValueError(f"{label}必须大于 0。")
        return parsed

    @staticmethod
    def _parse_positive_int(value: str, label: str, *, allow_zero: bool = False) -> int:
        normalized = value.strip().replace(",", "")
        if not normalized.isdigit():
            raise ValueError(f"{label}必须是整数。")
        parsed = int(normalized)
        if allow_zero:
            if parsed < 0:
                raise ValueError(f"{label}不能小于 0。")
        elif parsed <= 0:
            raise ValueError(f"{label}必须大于 0。")
        return parsed

    def _start_writing(self) -> None:
        if not self.settings.get("api_key"):
            messagebox.showwarning("提示", "请先在『设置』里填写并保存 API 密钥。")
            self.show_page("settings")
            return
        if not is_activated():
            messagebox.showwarning("提示", "请先激活授权。")
            self.show_page("settings")
            return
        title = self.title_entry.get().strip()
        custom_tags = self._parse_custom_tags(self.custom_tags_entry.get())
        if not custom_tags:
            messagebox.showwarning("提示", "请填写『作品标签』。")
            return
        audience = self.audience_var.get().strip()
        if audience not in {"男频", "女频"}:
            messagebox.showwarning("提示", "目标读者必须选择男频或女频。")
            return
        synopsis = self.synopsis_input.get("1.0", "end").strip()
        if len(synopsis) > 500:
            messagebox.showwarning("提示", "作品简介不能超过 500 字。")
            return
        if self.chapter_count_var.get() < 50:
            messagebox.showwarning("提示", "章节数太少，至少 50 章。")
            return
        try:
            input_token_limit = self._parse_token_limit(
                self.input_token_limit_var.get(), "输入token限制"
            )
            output_token_limit = self._parse_token_limit(
                self.output_token_limit_var.get(), "输出token限制"
            )
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        if input_token_limit <= INPUT_TOKEN_SAFETY_MARGIN:
            messagebox.showwarning("提示", "输入token限制太小，请填大一点。")
            return

        project = NovelProject()
        project.title = title
        project.custom_tags = custom_tags
        project.audience = audience
        project.synopsis = synopsis
        project.total_chapters = int(self.chapter_count_var.get())
        project.words_per_chapter = int(self.words_per_chapter_var.get())
        project.min_quality_score = int(self.min_quality_score_var.get())
        project.input_token_limit = input_token_limit
        project.output_token_limit = output_token_limit
        project.reasoning_effort = self.settings.get("reasoning_effort", "high")
        project.thinking_enabled = bool(self.settings.get("thinking_enabled", True))
        project.model = self.settings.get("model", "deepseek-v4-flash")
        project.ask_each_chapter = bool(self.ask_each_chapter_var.get())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project.save_path = str(PROJECTS_DIR / f"novel_{timestamp}_{project.project_id}")
        project.save()
        self._launch_engine(project)

    @staticmethod
    def _parse_custom_tags(raw: str) -> list[str]:

        result: list[str] = []
        seen: set[str] = set()
        if not raw:
            return result
        normalized = raw
        for sep in ["，", "、", ";", "；", "\n", "\t", " "]:
            normalized = normalized.replace(sep, ",")
        for chunk in normalized.split(","):
            tag = chunk.strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            result.append(tag)
        return result

    def _launch_engine(self, project: NovelProject) -> None:
        if self.writing_thread is not None and self.writing_thread.is_alive():
            messagebox.showwarning("提示", "已有任务在写作中，请先停止。")
            return

        self.project = project
        self.engine = NovelEngine(
            api_key=self.settings["api_key"],
            project=project,
            model=self.settings.get("model", "deepseek-v4-flash"),
            reasoning_effort=self.settings.get("reasoning_effort", "high"),
            thinking_enabled=bool(self.settings.get("thinking_enabled", True)),
        )

        self._reset_progress_ui(project)
        self._writing_start_time = time.time()
        self.show_page("progress")

        def _run() -> None:
            self.engine.run(
                on_status=lambda m: self.after(0, self._ui_status, m),
                on_chapter_start=lambda n, t: self.after(0, self._ui_chapter_start, n, t),
                on_chunk=self._on_chunk,
                on_chapter_complete=lambda n, w: self.after(0, self._ui_chapter_done, n, w),
                on_chapter_feedback=self._ask_chapter_direction,
                on_complete=lambda: self.after(0, self._ui_complete),
                on_error=lambda e: self.after(0, self._ui_error, e),
            )

        self.writing_thread = threading.Thread(target=_run, daemon=True)
        self.writing_thread.start()

    def _ask_chapter_direction(self, chapter_num: int, title: str) -> str | None:
        result: dict[str, str | None] = {"value": None}
        event = threading.Event()

        def ask() -> None:
            dialog = ctk.CTkInputDialog(
                title="下一章方向",
                text=(
                    f"第 {chapter_num} 章《{title}》已完成。\n"
                    "请输入下一章希望发展的方向；留空或取消则自动继续。"
                ),
            )
            result["value"] = dialog.get_input()
            event.set()

        self.after(0, ask)
        event.wait()
        return result["value"]

    def _reset_progress_ui(self, project: NovelProject) -> None:
        self.progress_text.configure(state="normal")
        self.progress_text.delete("1.0", "end")
        self.progress_text.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_pct.configure(
            text=f"0 / {project.total_chapters} (0.00%)"
        )
        self.stat_chapters.configure(text="已完成：0 章")
        self.stat_words.configure(text="总字数：0")
        self.stat_avg.configure(text="均字数：0")
        self.stat_title.configure(text=f"《{project.title or '未命名'}》")
        self.status_label.configure(text="正在启动…")
        self.btn_pause.configure(state="normal")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._chapter_text_chars = 0

        initial_synopsis = project.synopsis or "（AI 正在为本书设计独特的设定与简介，请稍候…）"
        self._show_synopsis(initial_synopsis)

    def _show_synopsis(self, text: str) -> None:
        if not text:
            return
        self.synopsis_text.configure(state="normal")
        current = self.synopsis_text.get("1.0", "end").strip()
        if current == text.strip():
            self.synopsis_text.configure(state="disabled")
            return
        self.synopsis_text.delete("1.0", "end")
        self.synopsis_text.insert("1.0", text)
        self.synopsis_text.configure(state="disabled")

    def _copy_synopsis(self) -> None:
        text = self.synopsis_text.get("1.0", "end").strip()
        if not text or text.startswith("（"):
            messagebox.showinfo("提示", "简介还没生成完，请等 AI 生成完原创设定后再复制。")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("已复制", f"作品简介（{len(text)} 字）已复制到剪贴板。")





    def _build_progress_page(self) -> None:
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["progress"] = page
        page.grid_rowconfigure(3, weight=1)
        page.grid_columnconfigure(0, weight=1)


        top = ctk.CTkFrame(page, fg_color=("gray90", "gray20"), corner_radius=10)
        top.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 5))

        self.status_label = ctk.CTkLabel(
            top, text="就绪",
            font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
        )
        self.status_label.pack(anchor="w", padx=15, pady=(10, 5))

        bar_frame = ctk.CTkFrame(top, fg_color="transparent")
        bar_frame.pack(fill="x", padx=15, pady=(0, 10))
        self.progress_bar = ctk.CTkProgressBar(
            bar_frame, height=18, corner_radius=8,
        )
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_bar.set(0)
        self.progress_pct = ctk.CTkLabel(
            bar_frame, text="0 / 0 (0.00%)",
            font=ctk.CTkFont(family=FONT, size=13),
        )
        self.progress_pct.pack(side="right")


        synopsis_card = ctk.CTkFrame(page, fg_color=("gray90", "gray20"), corner_radius=10)
        synopsis_card.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
        synopsis_card.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(synopsis_card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(
            header, text="作品简介",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header, text="复制简介", width=90, height=28,
            font=ctk.CTkFont(family=FONT, size=12),
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray35"),
            command=self._copy_synopsis,
        ).pack(side="right")
        self.synopsis_text = ctk.CTkTextbox(
            synopsis_card, height=110,
            font=ctk.CTkFont(family=FONT, size=13),
            wrap="word", state="disabled", corner_radius=6,
        )
        self.synopsis_text.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))


        stats = ctk.CTkFrame(page, fg_color=("gray90", "gray20"), corner_radius=10)
        stats.grid(row=2, column=0, sticky="ew", padx=15, pady=5)
        stats_inner = ctk.CTkFrame(stats, fg_color="transparent")
        stats_inner.pack(padx=15, pady=8, fill="x")

        self.stat_title = ctk.CTkLabel(
            stats_inner, text="",
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
            text_color=("#E94560", "#E94560"),
        )
        self.stat_title.pack(side="left", padx=(0, 28))
        self.stat_chapters = ctk.CTkLabel(
            stats_inner, text="已完成：0 章",
            font=ctk.CTkFont(family=FONT, size=13),
        )
        self.stat_chapters.pack(side="left", padx=(0, 28))
        self.stat_words = ctk.CTkLabel(
            stats_inner, text="总字数：0",
            font=ctk.CTkFont(family=FONT, size=13),
        )
        self.stat_words.pack(side="left", padx=(0, 28))
        self.stat_avg = ctk.CTkLabel(
            stats_inner, text="均字数：0",
            font=ctk.CTkFont(family=FONT, size=13),
        )
        self.stat_avg.pack(side="left", padx=(0, 28))
        self.stat_elapsed = ctk.CTkLabel(
            stats_inner, text="运行 0 s",
            font=ctk.CTkFont(family=FONT, size=13),
        )
        self.stat_elapsed.pack(side="left")


        self.progress_text = ctk.CTkTextbox(
            page,
            font=ctk.CTkFont(family=FONT, size=14),
            wrap="word", state="disabled", corner_radius=10,
        )
        self.progress_text.grid(row=3, column=0, sticky="nsew", padx=15, pady=5)


        ctrl = ctk.CTkFrame(page, fg_color="transparent")
        ctrl.grid(row=4, column=0, pady=(5, 15))
        self.btn_pause = ctk.CTkButton(
            ctrl, text="⏸  暂停", width=140, height=42,
            font=ctk.CTkFont(family=FONT, size=14),
            fg_color=("#F39C12", "#D68910"),
            hover_color=("#E67E22", "#CA6F1E"),
            command=self._pause_writing, state="disabled",
        )
        self.btn_pause.pack(side="left", padx=8)
        self.btn_resume = ctk.CTkButton(
            ctrl, text="▶  继续", width=140, height=42,
            font=ctk.CTkFont(family=FONT, size=14),
            fg_color=("#2ECC71", "#27AE60"),
            hover_color=("#27AE60", "#229954"),
            command=self._resume_writing, state="disabled",
        )
        self.btn_resume.pack(side="left", padx=8)
        self.btn_stop = ctk.CTkButton(
            ctrl, text="⏹  停止", width=140, height=42,
            font=ctk.CTkFont(family=FONT, size=14),
            fg_color=("#E74C3C", "#C0392B"),
            hover_color=("#C0392B", "#A93226"),
            command=self._stop_writing, state="disabled",
        )
        self.btn_stop.pack(side="left", padx=8)
        ctk.CTkButton(
            ctrl, text="清空显示", width=120, height=42,
            font=ctk.CTkFont(family=FONT, size=13),
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray35"),
            command=self._clear_progress_text,
        ).pack(side="left", padx=8)

    def _on_chunk(self, text: str) -> None:
        if text:
            self._chunk_queue.put(text)

    def _poll_chunk_queue(self) -> None:
        batch: list[str] = []
        while True:
            try:
                batch.append(self._chunk_queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            joined = "".join(batch)
            self._chapter_text_chars += len(joined)
            follow_scroll = _should_follow_progress_scroll(self.progress_text.yview())
            self.progress_text.configure(state="normal")
            self.progress_text.insert("end", joined)
            if follow_scroll:
                self.progress_text.see("end")
            self.progress_text.configure(state="disabled")
        self.after(80, self._poll_chunk_queue)

    def _tick_elapsed(self) -> None:
        if self._writing_start_time and self.engine is not None:
            elapsed = int(time.time() - self._writing_start_time)
            if elapsed < 60:
                text = f"运行 {elapsed} s"
            elif elapsed < 3600:
                text = f"运行 {elapsed // 60} 分 {elapsed % 60} 秒"
            else:
                text = f"运行 {elapsed // 3600} 小时 {(elapsed % 3600) // 60} 分"
            self.stat_elapsed.configure(text=text)
        self.after(1000, self._tick_elapsed)

    def _pause_writing(self) -> None:
        if self.engine is not None:
            self.engine.pause()
            self.status_label.configure(text="已暂停（当前流式调用结束后会真正停顿）")
            self.btn_pause.configure(state="disabled")
            self.btn_resume.configure(state="normal")

    def _resume_writing(self) -> None:
        if self.engine is not None:
            self.engine.resume()
            self.status_label.configure(text="继续写作中…")
            self.btn_pause.configure(state="normal")
            self.btn_resume.configure(state="disabled")

    def _stop_writing(self) -> None:
        if self.engine is not None:
            self.engine.stop()
            self.status_label.configure(text="已停止")
            self.btn_pause.configure(state="disabled")
            self.btn_resume.configure(state="disabled")
            self.btn_stop.configure(state="disabled")

    def _clear_progress_text(self) -> None:
        self.progress_text.configure(state="normal")
        self.progress_text.delete("1.0", "end")
        self.progress_text.configure(state="disabled")





    def _ui_status(self, msg: str) -> None:
        self.status_label.configure(text=msg)
        if self.project and self.project.title:
            self.stat_title.configure(text=f"《{self.project.title}》")
        if self.project and self.project.synopsis:
            self._show_synopsis(self.project.synopsis)

    def _ui_chapter_start(self, chapter_num: int, total: int) -> None:
        self.status_label.configure(text=f"正在写作第 {chapter_num} 章…")
        follow_scroll = _should_follow_progress_scroll(self.progress_text.yview())
        self.progress_text.configure(state="normal")
        self.progress_text.insert("end", f"\n\n━━━━ 第 {chapter_num} 章 ━━━━\n\n")
        if follow_scroll:
            self.progress_text.see("end")
        self.progress_text.configure(state="disabled")
        self._chapter_text_chars = 0

    def _ui_chapter_done(self, chapter_num: int, char_count: int) -> None:
        if not self.project:
            return
        total = self.project.total_chapters
        pct = chapter_num / total if total else 0
        self.progress_bar.set(pct)
        self.progress_pct.configure(
            text=f"{chapter_num} / {total}  ({pct:.2%})"
        )
        self.stat_chapters.configure(text=f"已完成：{chapter_num} 章")
        total_words = self.project.total_words
        self.stat_words.configure(text=f"总字数：{total_words:,}")
        avg = total_words // chapter_num if chapter_num else 0
        self.stat_avg.configure(text=f"均字数：{avg:,}")

    def _ui_complete(self) -> None:
        self.status_label.configure(text="全部章节创作完成！")
        self.btn_pause.configure(state="disabled")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        if self.project:
            messagebox.showinfo(
                "完成",
                f"《{self.project.title}》全部创作完成！\n"
                f"共 {self.project.total_words:,} 字，"
                f"项目目录：{self.project.save_path}",
            )

    def _ui_error(self, msg: str) -> None:
        self.status_label.configure(text=f"出错：{msg[:160]}")
        self.btn_pause.configure(state="disabled")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        messagebox.showerror("错误", msg)





    def _build_library_page(self) -> None:
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.pages["library"] = page
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, minsize=300)
        page.grid_columnconfigure(1, minsize=240)
        page.grid_columnconfigure(2, weight=1)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=15, pady=(15, 5))
        ctk.CTkLabel(
            header, text="作品库",
            font=ctk.CTkFont(family=FONT, size=22, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header, text="刷新", width=90, height=32,
            font=ctk.CTkFont(family=FONT, size=12),
            command=self._refresh_library,
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            header, text="导出 TXT", width=100, height=32,
            font=ctk.CTkFont(family=FONT, size=12),
            fg_color=("#2ECC71", "#27AE60"),
            command=self._export_novel,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            header, text="继续写作", width=100, height=32,
            font=ctk.CTkFont(family=FONT, size=12),
            fg_color=("#F39C12", "#D68910"),
            command=self._resume_project,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            header, text="打开项目目录", width=120, height=32,
            font=ctk.CTkFont(family=FONT, size=12),
            command=self._open_lib_project_dir,
        ).pack(side="left", padx=4)

        proj_frame = ctk.CTkFrame(page, corner_radius=10)
        proj_frame.grid(row=1, column=0, sticky="nsew", padx=(15, 5), pady=5)
        ctk.CTkLabel(
            proj_frame, text="项目列表",
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
        ).pack(padx=10, pady=(8, 4), anchor="w")
        self.project_list = ctk.CTkScrollableFrame(proj_frame, fg_color="transparent")
        self.project_list.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        ch_frame = ctk.CTkFrame(page, corner_radius=10)
        ch_frame.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        ctk.CTkLabel(
            ch_frame, text="章节列表",
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
        ).pack(padx=10, pady=(8, 4), anchor="w")
        self.chapter_list = ctk.CTkScrollableFrame(ch_frame, fg_color="transparent")
        self.chapter_list.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        self.chapter_viewer = ctk.CTkTextbox(
            page,
            font=ctk.CTkFont(family=FONT, size=14),
            wrap="word", state="disabled", corner_radius=10,
        )
        self.chapter_viewer.grid(row=1, column=2, sticky="nsew", padx=(5, 15), pady=5)

    def _refresh_library(self) -> None:
        for w in self.project_list.winfo_children():
            w.destroy()
        for w in self.chapter_list.winfo_children():
            w.destroy()
        self.chapter_viewer.configure(state="normal")
        self.chapter_viewer.delete("1.0", "end")
        self.chapter_viewer.configure(state="disabled")
        self._lib_project = None

        paths = NovelProject.list_projects(PROJECTS_DIR)
        if not paths:
            ctk.CTkLabel(
                self.project_list,
                text="还没有作品。先去『新建小说』开始第一本。",
                font=ctk.CTkFont(family=FONT, size=12),
                text_color="gray60",
            ).pack(padx=10, pady=10)
            return

        status_map = {
            "new": "新建", "planning": "规划中",
            "writing": "写作中", "paused": "已暂停",
            "completed": "已完成", "error": "出错",
        }
        for path in paths:
            try:
                proj = NovelProject.load(path)
            except (OSError, ValueError, FileNotFoundError):
                continue
            label = (
                f"《{proj.title or '未命名'}》  "
                f"{proj.current_chapter}/{proj.total_chapters} 章  "
                f"[{status_map.get(proj.status, proj.status)}]"
            )
            btn = ctk.CTkButton(
                self.project_list, text=label, anchor="w",
                height=38, corner_radius=6,
                font=ctk.CTkFont(family=FONT, size=12),
                fg_color="transparent",
                hover_color=("gray75", "gray25"),
                command=lambda p=path: self._select_project(p),
            )
            btn.pack(fill="x", pady=1)

    def _select_project(self, path: str) -> None:
        try:
            proj = NovelProject.load(path)
        except (OSError, ValueError, FileNotFoundError) as exc:
            messagebox.showerror("错误", f"加载项目失败：{exc}")
            return
        self._lib_project = proj
        for w in self.chapter_list.winfo_children():
            w.destroy()


        self._show_project_synopsis()


        ctk.CTkButton(
            self.chapter_list,
            text="📖  作品介绍 / 简介",
            anchor="w", height=32, corner_radius=4,
            font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
            fg_color=("#3B8ED0", "#1F6AA5"),
            hover_color=("#3679B0", "#1A5A8E"),
            command=self._show_project_synopsis,
        ).pack(fill="x", pady=2)

        if not proj.chapters:
            ctk.CTkLabel(
                self.chapter_list, text="（暂无章节）",
                font=ctk.CTkFont(family=FONT, size=12),
                text_color="gray60",
            ).pack(padx=10, pady=10)
            return

        for num in sorted(proj.chapters.keys(), key=lambda x: int(x)):
            ch = proj.chapters[num]
            title = ch.get("title", f"第{num}章")
            wc = ch.get("word_count", 0)
            btn = ctk.CTkButton(
                self.chapter_list,
                text=f"第{num}章 {title}  ({wc} 字)",
                anchor="w", height=30, corner_radius=4,
                font=ctk.CTkFont(family=FONT, size=11),
                fg_color="transparent",
                hover_color=("gray75", "gray25"),
                command=lambda n=num: self._show_chapter(n),
            )
            btn.pack(fill="x", pady=1)

    def _show_chapter(self, num: str) -> None:
        if not self._lib_project:
            return
        ch = self._lib_project.chapters.get(num, {})
        self.chapter_viewer.configure(state="normal")
        self.chapter_viewer.delete("1.0", "end")
        title = ch.get("title", "")
        body = ch.get("content", "（无内容）")
        self.chapter_viewer.insert("1.0", f"第{num}章 {title}\n\n{body}")
        self.chapter_viewer.configure(state="disabled")

    def _show_project_synopsis(self) -> None:
        if not self._lib_project:
            return
        synopsis = self._lib_project.synopsis or "（这本书还没生成简介。）"
        title = self._lib_project.title or "未命名"
        audience = self._lib_project.audience or "未指定"
        tags = "、".join(self._lib_project.merged_tags()) or "（无）"
        self.chapter_viewer.configure(state="normal")
        self.chapter_viewer.delete("1.0", "end")
        self.chapter_viewer.insert(
            "1.0",
            (
                f"《{title}》\n\n"
                f"目标读者：{audience}\n"
                f"题材标签：{tags}\n\n"
                f"作品简介（{len(synopsis)} 字）：\n{synopsis}\n"
            ),
        )
        self.chapter_viewer.configure(state="disabled")

    def _export_novel(self) -> None:
        proj = self._lib_project or self.project
        if proj is None:
            messagebox.showwarning("提示", "请先选择一个项目。")
            return
        proj.refresh()
        if not proj.chapters:
            messagebox.showwarning("提示", "项目还没有任何章节。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
            initialfile=f"《{proj.title or '未命名'}》.txt",
        )
        if not path:
            return
        try:
            proj.export_txt(path)
        except FileNotFoundError as exc:
            messagebox.showerror("错误", str(exc))
            return
        messagebox.showinfo("成功", f"已导出到：{path}")

    def _resume_project(self) -> None:
        if not self._lib_project:
            messagebox.showwarning("提示", "请先在左边选一个项目。")
            return
        proj = self._lib_project
        if proj.status == "completed":
            messagebox.showinfo("提示", "该项目已完成。")
            return
        if not self.settings.get("api_key"):
            messagebox.showwarning("提示", "请先在『设置』里填写 API 密钥。")
            self.show_page("settings")
            return
        if not is_activated():
            messagebox.showwarning("提示", "请先激活授权。")
            self.show_page("settings")
            return
        self._show_resume_options_dialog(proj)

    def _show_resume_options_dialog(self, proj: NovelProject) -> None:
        win = ctk.CTkToplevel(self)
        win.title("续写前确认参数")
        win.geometry("560x560")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=22)

        ctk.CTkLabel(
            body,
            text="续写前确认参数",
            font=ctk.CTkFont(family=FONT, size=22, weight="bold"),
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(
            body,
            text=(
                f"当前项目：《{proj.title or '未命名'}》，已完成 {proj.current_chapter} 章。"
                "下面参数只影响后续未完成章节，已经写完的章节不会自动重写。"
            ),
            font=ctk.CTkFont(family=FONT, size=12),
            text_color="gray60",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(0, 16))

        fields = ctk.CTkFrame(body, fg_color=("gray90", "gray18"), corner_radius=10)
        fields.pack(fill="x", pady=(0, 12))

        values: dict[str, ctk.StringVar] = {
            "total_chapters": ctk.StringVar(value=str(proj.total_chapters)),
            "words_per_chapter": ctk.StringVar(value=str(proj.words_per_chapter)),
            "input_token_limit": ctk.StringVar(value=str(proj.input_token_limit)),
            "output_token_limit": ctk.StringVar(value=str(proj.output_token_limit)),
            "min_quality_score": ctk.StringVar(value=str(proj.min_quality_score)),
        }

        def add_entry(label: str, key: str, row: int) -> None:
            line = ctk.CTkFrame(fields, fg_color="transparent")
            line.pack(fill="x", padx=14, pady=(10 if row == 0 else 6, 0))
            ctk.CTkLabel(
                line,
                text=label,
                width=150,
                anchor="w",
                font=ctk.CTkFont(family=FONT, size=12),
            ).pack(side="left")
            ctk.CTkEntry(
                line,
                textvariable=values[key],
                width=160,
                height=30,
                font=ctk.CTkFont(family="Consolas", size=12),
            ).pack(side="left")

        add_entry("目标章节数量", "total_chapters", 0)
        add_entry("每章字数", "words_per_chapter", 1)
        add_entry("输入token限制", "input_token_limit", 2)
        add_entry("输出token限制", "output_token_limit", 3)

        option_line = ctk.CTkFrame(fields, fg_color="transparent")
        option_line.pack(fill="x", padx=14, pady=(10, 8))
        ctk.CTkLabel(
            option_line,
            text="目标质量分",
            width=150,
            anchor="w",
            font=ctk.CTkFont(family=FONT, size=12),
        ).pack(side="left")
        ctk.CTkOptionMenu(
            option_line,
            width=80,
            height=30,
            values=["70", "75", "80", "82", "85", "88", "90", "92", "95", "98"],
            variable=values["min_quality_score"],
            font=ctk.CTkFont(family=FONT, size=12),
        ).pack(side="left")

        ctk.CTkLabel(
            body,
            text=(
                "输入token限制是每次写作最多参考多少上文、设定、摘要和本章方向。"
                "输出token限制是模型一次最多生成多少内容。"
                "两者合计最好不要超过 1M。"
            ),
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="gray60",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(
            actions,
            text="取消",
            width=120,
            height=40,
            fg_color=("gray70", "gray30"),
            command=win.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            actions,
            text="保存参数并继续写作",
            width=210,
            height=40,
            fg_color=("#F39C12", "#D68910"),
            command=lambda: self._apply_resume_options_and_launch(proj, values, win),
        ).pack(side="right")

    def _apply_resume_options_and_launch(
        self,
        proj: NovelProject,
        values: dict[str, ctk.StringVar],
        win: ctk.CTkToplevel,
    ) -> None:
        try:
            total_chapters = self._parse_positive_int(values["total_chapters"].get(), "目标章节数量")
            words_per_chapter = self._parse_positive_int(values["words_per_chapter"].get(), "每章字数")
            input_token_limit = self._parse_token_limit(values["input_token_limit"].get(), "输入token限制")
            output_token_limit = self._parse_token_limit(values["output_token_limit"].get(), "输出token限制")
            min_quality_score = self._parse_positive_int(values["min_quality_score"].get(), "最低质量分")
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc), parent=win)
            return

        if total_chapters < 50 or total_chapters > 10000:
            messagebox.showwarning("提示", "目标章节数量必须在 50 到 10000 之间。", parent=win)
            return
        if total_chapters <= proj.current_chapter:
            messagebox.showwarning("提示", f"目标章节数量必须大于已完成章节数 {proj.current_chapter}。", parent=win)
            return
        if words_per_chapter < 1000 or words_per_chapter > 20000:
            messagebox.showwarning("提示", "每章字数必须在 1000 到 20000 之间。", parent=win)
            return
        if input_token_limit <= INPUT_TOKEN_SAFETY_MARGIN:
            messagebox.showwarning("提示", "输入token限制太小，请填大一点。", parent=win)
            return
        if input_token_limit + output_token_limit > 1_000_000:
            ok = messagebox.askyesno(
                "确认",
                "输入token限制 + 输出token限制已经超过 1M，可能导致模型接口失败。确定还要继续吗？",
                parent=win,
            )
            if not ok:
                return

        proj.total_chapters = total_chapters
        proj.words_per_chapter = words_per_chapter
        proj.input_token_limit = input_token_limit
        proj.output_token_limit = output_token_limit
        proj.min_quality_score = min_quality_score
        proj.save()
        proj.refresh()
        self._lib_project = proj
        win.destroy()
        self._launch_engine(proj)

    def _open_lib_project_dir(self) -> None:
        if not self._lib_project:
            messagebox.showwarning("提示", "请先在左边选一个项目。")
            return
        self._open_path(Path(self._lib_project.save_path))

    def _open_projects_root(self) -> None:
        self._open_path(PROJECTS_DIR)

    def _open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')


def main() -> None:
    _bootstrap_app_dirs()
    app = NovelWriterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
