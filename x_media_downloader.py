#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X (Twitter) 博主图片 / 视频下载器
--------------------------------
功能：
  1. 输入博主账号名（支持多个，逗号或空格分隔）
  2. 选择下载：仅图片 / 仅视频 / 图片与视频
  3. 选择时间范围：全部 / 最近 N 天 / 自定义起止日期
  4. 选择保存文件夹（自动按账号名分目录）
  5. 支持 cookies、代理、限速、断点续传、数量上限

底层引擎：gallery-dl（首次运行会自动安装）
依赖：Python 3.8+  （Tkinter 为 Python 标准库，无需额外安装）
"""

import ctypes
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import date, datetime, timedelta

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ---------------------------------------------------------------- 基础配置

APP_NAME = "X (Twitter) 媒体下载器"
APP_VERSION = "1.1.0"
IS_FROZEN = bool(getattr(sys, "frozen", False))   # PyInstaller 打包后的桌面版


def _app_dir():
    """程序所在目录（桌面版 = exe 所在目录）"""
    if IS_FROZEN:
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _config_dir():
    """配置文件目录：桌面版放 %APPDATA%，避免装在 C:\\Program Files 时无写入权限"""
    if IS_FROZEN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "XMediaDownloader")
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            pass
    return _app_dir()


BASE_DIR = _app_dir()
CONFIG_FILE = os.path.join(_config_dir(), ".x_downloader_config.json")
DEFAULT_DEST = os.path.join(BASE_DIR, "downloads")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
CREATE_NO_WINDOW = 0x08000000  # Windows: 不弹出黑框

# 文件类型过滤表达式（gallery-dl 的 file 级 filter）
TYPE_FILTER = {
    "image": "locals().get('type') in ('photo',)",
    "video": "locals().get('type') in ('video', 'animated_gif')",
    "both": None,
}
TYPE_LABEL = {"image": "仅图片", "video": "仅视频", "both": "图片与视频"}

PREVIEW_TIMEOUT = 120      # 统计文件数量最多等 120 秒

# 代理自动检测相关
TEST_URL = "https://api.x.com/"      # 只要能收到 HTTP 响应（含 404）即说明链路通
CLASH_DIRS = (
    "~/.config/clash-verge/profiles",
    "~/.config/clash-verge",
    "~/.config/clash",
    "~/AppData/Roaming/Clash for Windows",
    "~/AppData/Roaming/clash-verge",
    "~/AppData/Roaming/Clash Verge",
)
CANDIDATE_PORTS = (7890, 7897, 7891, 7892, 7893, 10809, 10808, 1080,
                   20171, 8889, 2080, 8080)

# macOS 风格配色（浅色）
BG = "#f5f5f7"          # 窗口背景
SIDEBAR_BG = "#ededf0"  # 侧边栏
CARD = "#ffffff"        # 卡片
BORDER = "#e1e1e6"      # 卡片描边
SEP = "#d8d8dc"         # 分隔线
TEXT = "#1d1d1f"        # 主文字
TEXT2 = "#86868b"       # 次要文字
ACCENT = "#007aff"      # 系统蓝
OK = "#34c759"
WARN = "#ff9500"
ERR = "#ff3b30"
UI_FONT = "Segoe UI"


def clean(line: str) -> str:
    """去掉 ANSI 颜色控制符"""
    return ANSI_RE.sub("", line).rstrip()


def parse_date(text_value: str):
    """解析 YYYY-MM-DD，失败返回 None"""
    text_value = (text_value or "").strip()
    if not text_value:
        return None
    try:
        return datetime.strptime(text_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def http_probe(proxy: str, timeout: int = 8, url: str = TEST_URL):
    """通过（或不用）代理访问测试地址。收到任何 HTTP 响应都算链路通。"""
    import urllib.error
    import urllib.request
    try:
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        else:
            opener = urllib.request.build_opener()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:   # 404/403 等都说明链路是通的
        return True, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:70]}"


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _system_proxy_windows():
    """读取 Windows 系统代理（Clash 开启系统代理后会写在这里）"""
    if os.name != "nt":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if not server:
            return None
        server = server.strip()
        if "=" in server:                      # http=...;https=...;socks=...
            for part in server.split(";"):
                if part.lower().startswith(("http=", "https=")):
                    host = part.split("=", 1)[1]
                    return host if "://" in host else "http://" + host
            return None
        return server if "://" in server else "http://" + server
    except Exception:  # noqa: BLE001
        return None


def _clash_ports():
    """从 Clash 的配置/订阅文件里找 mixed-port / port"""
    ports, seen = [], set()
    for d in CLASH_DIRS:
        folder = os.path.expanduser(d)
        if not os.path.isdir(folder):
            continue
        names = [n for n in os.listdir(folder)
                 if n.lower().endswith((".yaml", ".yml"))][:6]
        for name in names:
            try:
                with open(os.path.join(folder, name), "r", encoding="utf-8",
                          errors="ignore") as fp:
                    head = fp.read(6000)
            except Exception:  # noqa: BLE001
                continue
            for m in re.finditer(r"(?:mixed-port|port|http-port)\s*:\s*(\d+)", head):
                try:
                    p = int(m.group(1))
                except ValueError:
                    continue
                if p not in seen and 1 < p < 65536:
                    seen.add(p)
                    ports.append(p)
    return ports


def auto_detect_proxy(logger=None, timeout: int = 8):
    """自动找出可用的代理。返回 (proxy, 来源)；proxy 为空串表示可直连。

    顺序（快的先来，避免无效等待）：
      本机已监听的 Clash/常见端口 → 系统代理 → 环境变量 → 直连
    """
    def log(msg):
        if logger:
            logger("  " + msg, "dim")

    tried = set()

    def probe(proxy, label, t=6):
        if proxy in tried:
            return False
        tried.add(proxy)
        ok, detail = http_probe(proxy, t)
        log(f"{label} → {detail}")
        if ok:
            log(f"✔ 采用：{proxy or '直连'}（{label}）")
            return True
        return False

    # 1) 本机已监听的代理端口（TCP 探测只要 0.3 秒，最快）
    ports = []
    for p in _clash_ports() + list(CANDIDATE_PORTS):
        if p not in ports:
            ports.append(p)
    opened = [p for p in ports if _port_open("127.0.0.1", p)]
    log(f"本机监听中的代理端口：{opened or '无'}")
    for port in opened:
        if probe(f"http://127.0.0.1:{port}", f"本机端口 {port}"):
            return f"http://127.0.0.1:{port}", f"本机端口 {port}"

    # 2) Windows 系统代理（Clash 开启系统代理后写在这里）
    sp = _system_proxy_windows()
    if sp and probe(sp, f"系统代理 {sp}"):
        return sp, "Windows 系统代理（Clash 写入）"

    # 3) 环境变量（去重，且端口没监听的直接跳过）
    for key in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY",
                "http_proxy", "HTTP_PROXY"):
        val = os.environ.get(key)
        if not val:
            continue
        p = val if "://" in val else "http://" + val
        if probe(p, f"环境变量 {key}"):
            return p, f"环境变量 {key}"

    # 4) 直连（Clash 开了 TUN / 全局模式时可用）
    if probe("", "直连", min(timeout, 6)):
        return "", "直连可用（Clash 可能开了 TUN / 全局模式）"

    return None, "直连失败，且本机没探测到可用的 Clash / 系统代理端口"


# ---------------------------------------------------------------- 引擎管理

def gallery_dl_module_available() -> bool:
    return importlib.util.find_spec("gallery_dl") is not None


def resource_path(rel):
    """打包后资源文件所在目录（PyInstaller 临时目录 / exe 同目录）"""
    for base in (getattr(sys, "_MEIPASS", None), BASE_DIR):
        if base:
            path = os.path.join(base, rel)
            if os.path.exists(path):
                return path
    return os.path.join(BASE_DIR, rel)


def bundled_gdl_path():
    """桌面版内置的下载引擎启动器路径（gdl.exe），未打包时返回 None"""
    if not IS_FROZEN:
        return None
    here = os.path.dirname(sys.executable)
    for rel in ("gdl.exe", os.path.join("_internal", "gdl.exe"), "gdl"):
        path = os.path.join(here, rel)
        if os.path.isfile(path):
            return path
    return None


def build_base_command() -> list:
    """优先用打包内置的引擎，其次当前 Python 的模块方式，最后 PATH 里的 gallery-dl"""
    bundled = bundled_gdl_path()
    if bundled:
        return [bundled]
    if gallery_dl_module_available():
        return [sys.executable, "-m", "gallery_dl"]
    exe = shutil.which("gallery-dl") or shutil.which("gallery-dl.exe")
    if exe:
        return [exe]
    return None


def install_gallery_dl(log):
    """自动安装下载引擎（桌面版已内置，无需安装）"""
    if IS_FROZEN:
        log("桌面版已内置下载引擎，无需安装。若仍提示缺失，请重新解压完整程序包。", "warn")
        return False
    pip_cmds = [
        [sys.executable, "-m", "pip", "install", "-U", "gallery-dl",
         "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
        [sys.executable, "-m", "pip", "install", "-U", "gallery-dl"],
    ]
    for cmd in pip_cmds:
        log("正在安装下载引擎 gallery-dl ...", "info")
        log("  $ " + " ".join(cmd), "dim")
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                startupinfo=_startup_info(), env=_child_env())
            for line in proc.stdout:
                log(clean(line), "dim")
            proc.wait()
        except Exception as exc:  # noqa: BLE001
            log(f"安装失败：{exc}", "error")
            continue
        if gallery_dl_module_available():
            log("gallery-dl 安装完成。", "ok")
            return True
    return False


def _startup_info():
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return info


def _child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"   # 关键：否则子进程输出被缓冲，界面日志一直空白
    return env


# ---------------------------------------------------------------- 主程序

# ---------------------------------------------------------------- 自绘控件

class RoundedButton(tk.Canvas):
    """圆角按钮：Canvas 自绘，文字一定会渲染（规避 ttk 偶发不显示文字）"""

    def __init__(self, master, text="Button", command=None, width=None,
                 height=34, bg=ACCENT, fg="#ffffff", hover_bg=None,
                 disabled_bg="#e5e5ea", disabled_fg="#a1a1a6", radius=7,
                 font=None, padx=18, state="normal", outline=""):
        import tkinter.font as tkfont
        font = font or (UI_FONT, 10)
        w = width or (tkfont.Font(font=font).measure(text) + padx * 2)
        try:
            m_bg = master.cget("bg")
        except Exception:
            m_bg = BG
        tk.Canvas.__init__(self, master, width=w, height=height,
                           bg=m_bg or BG, highlightthickness=0, bd=0)
        self.command = command
        self.text = text
        self.bg, self.fg = bg, fg
        self.hover_bg = hover_bg or _shade(bg, -18)
        self.press_bg = _shade(bg, -34)
        self.disabled_bg, self.disabled_fg = disabled_bg, disabled_fg
        self.state = state
        self.outline = outline
        self._hover = False
        self._pressed = False
        self.rect = self._round_rect(1, 1, w - 1, height - 1, radius)
        self.txt = self.create_text(w / 2, height / 2, text=text, font=font)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._paint()

    def _round_rect(self, x1, y1, x2, y2, r):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, outline=self.outline)

    def _paint(self):
        if self.state == "disabled":
            fill, txt = self.disabled_bg, self.disabled_fg
        elif self._pressed:
            fill, txt = self.press_bg, self.fg
        elif self._hover:
            fill, txt = self.hover_bg, self.fg
        else:
            fill, txt = self.bg, self.fg
        self.itemconfig(self.rect, fill=fill)
        self.itemconfig(self.txt, fill=txt)

    def _on_press(self, _e):
        if self.state != "normal":
            return
        self._pressed = True
        self._paint()

    def _on_release(self, _e):
        if self.state != "normal":
            return
        self._pressed = False
        self._paint()
        if self.command:
            self.command()

    def _on_enter(self, _e):
        if self.state != "normal":
            return
        self._hover = True
        tk.Canvas.configure(self, cursor="hand2")
        self._paint()

    def _on_leave(self, _e):
        self._hover = False
        self._paint()

    def configure(self, **kw):
        if "state" in kw:
            self.state = kw["state"]
            self._paint()
        if "text" in kw:
            self.text = kw["text"]
            self.itemconfig(self.txt, text=self.text)
        if "bg" in kw:
            self.bg = kw["bg"]
            self.hover_bg = _shade(self.bg, -18)
            self.press_bg = _shade(self.bg, -34)
            self._paint()
        if "cursor" in kw:
            tk.Canvas.configure(self, cursor=kw["cursor"])

    config = configure

    def cget(self, key):
        return {"text": self.text, "state": self.state}.get(key, "")

    def __getitem__(self, key):
        return self.cget(key)

    def __setitem__(self, key, value):
        self.configure(**{key: value})


class NavItem(tk.Canvas):
    """侧边栏导航项"""

    def __init__(self, master, text, command=None, width=178, height=34):
        tk.Canvas.__init__(self, master, width=width, height=height,
                           bg=SIDEBAR_BG, highlightthickness=0, bd=0)
        self.command = command
        self.selected = False
        self._hover = False
        self.rect = self._round_rect(4, 2, width - 4, height - 2, 6)
        self.txt = self.create_text(18, height / 2, text=text, anchor="w",
                                    font=(UI_FONT, 10))
        self.bind("<ButtonRelease-1>", lambda e: self.command and self.command())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._paint()

    def _round_rect(self, x1, y1, x2, y2, r):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, outline="")

    def _on_enter(self, _e):
        self._hover = True
        tk.Canvas.configure(self, cursor="hand2")
        self._paint()

    def _on_leave(self, _e):
        self._hover = False
        self._paint()

    def set_selected(self, flag):
        self.selected = flag
        self._paint()

    def _paint(self):
        if self.selected:
            self.itemconfig(self.rect, fill=ACCENT)
            self.itemconfig(self.txt, fill="#ffffff")
        elif self._hover:
            self.itemconfig(self.rect, fill="#dcdce1")
            self.itemconfig(self.txt, fill=TEXT)
        else:
            self.itemconfig(self.rect, fill=SIDEBAR_BG)
            self.itemconfig(self.txt, fill=TEXT)


def _shade(color, delta):
    """把 #rrggbb 调亮/调暗"""
    try:
        c = color.lstrip("#")
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return color
    f = lambda v: max(0, min(255, v + delta))
    return "#%02x%02x%02x" % (f(r), f(g), f(b))


class DownloaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc = None
        self.stop_flag = threading.Event()
        self.msg_queue = queue.Queue()
        self.running = False
        self.total_downloaded = 0
        self.log_fp = None
        self.log_path = None
        self.file_errors = 0
        self.auth_needed = False
        self.detected_proxy = None
        self._detecting = False

        self._load_config()
        self._build_ui()
        self.root.after(100, self._drain_queue)
        self.root.after(400, self.detect_proxy)   # 开机自动找 Clash 代理

    # -------------------------------------------------- 配置存取
    def _load_config(self):
        self.cfg = {
            "accounts": "",
            "media_type": "both",
            "time_mode": "all",
            "days": "30",
            "date_from": "",
            "date_to": "",
            "dest": DEFAULT_DEST,
            "cookies": "",
            "browser": "",
            "proxy": "",
            "sleep": "1",
            "limit": "",
            "resume": True,
            "gif_as_image": False,
            "timeline": False,
            "metadata": False,
            "preview": True,
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as fp:
                    self.cfg.update(json.load(fp))
            except Exception:  # noqa: BLE001
                pass

    def _save_config(self):
        data = {
            "accounts": self.var_accounts.get(),
            "media_type": self.var_type.get(),
            "time_mode": self.var_time.get(),
            "days": self.var_days.get(),
            "date_from": self.var_from.get(),
            "date_to": self.var_to.get(),
            "dest": self.var_dest.get(),
            "cookies": self.var_cookies.get(),
            "browser": self.var_browser.get(),
            "proxy": self.var_proxy.get(),
            "sleep": self.var_sleep.get(),
            "limit": self.var_limit.get(),
            "resume": self.var_resume.get(),
            "gif_as_image": self.var_gif.get(),
            "timeline": self.var_timeline.get(),
            "metadata": self.var_meta.get(),
            "preview": self.var_preview.get(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------- 界面
    def _build_ui(self):
        self.root.title(f"{APP_NAME}  v{APP_VERSION}")
        self.root.geometry("1000x680")
        self.root.minsize(880, 560)
        self.root.configure(bg=BG)

        try:  # 窗口标题栏 / 任务栏图标
            self.root.iconbitmap(resource_path("app.ico"))
        except Exception:  # noqa: BLE001
            pass

        try:  # Windows 高清屏
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=CARD, foreground=TEXT,
                        font=(UI_FONT, 10))
        style.configure("Sub.TLabel", background=BG, foreground=TEXT2,
                        font=(UI_FONT, 9))
        style.configure("TCheckbutton", background=CARD, font=(UI_FONT, 10))
        style.configure("TRadiobutton", background=CARD, font=(UI_FONT, 10))
        style.configure("TButton", font=(UI_FONT, 10))
        style.configure("Horizontal.TProgressbar", background=ACCENT,
                        troughcolor="#e5e5ea", borderwidth=0,
                        lightcolor=ACCENT, darkcolor=ACCENT)

        # ---- 左侧边栏（始终可见，主操作按钮放这里）
        sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        # ---- 右侧内容区（多页叠加，切换显示）
        content = tk.Frame(self.root, bg=BG)
        content.pack(side="left", fill="both", expand=True)
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)

        self.pages = {}
        for key in ("download", "advanced", "logs", "files", "help"):
            frame = tk.Frame(content, bg=BG)
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = frame

        self._page_download(self.pages["download"])
        self._page_advanced(self.pages["advanced"])
        self._page_logs(self.pages["logs"])
        self._page_files(self.pages["files"])
        self._page_help(self.pages["help"])
        self._show_page("download")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -------------------------------------------------- 侧边栏
    def _build_sidebar(self, sidebar):
        head = tk.Frame(sidebar, bg=SIDEBAR_BG)
        head.pack(fill="x", padx=16, pady=(18, 14))
        tk.Label(head, text="X 下载器", bg=SIDEBAR_BG, fg=TEXT, anchor="w",
                 font=(UI_FONT, 14, "bold")).pack(fill="x")
        tk.Label(head, text="图片 / 视频批量抓取", bg=SIDEBAR_BG, fg=TEXT2,
                 anchor="w", font=(UI_FONT, 9)).pack(fill="x")

        self.nav_items = {}
        nav = [("download", "下载"), ("advanced", "高级设置"),
               ("logs", "运行日志"), ("files", "已下载"), ("help", "帮助")]
        for key, label in nav:
            item = NavItem(sidebar, label,
                           command=lambda k=key: self._show_page(k))
            item.pack(fill="x", padx=16, pady=1)
            self.nav_items[key] = item

        tk.Frame(sidebar, bg=SEP, height=1).pack(fill="x", padx=14, pady=12)

        # 底部固定区：状态 → 进度 → 按钮（窗口怎么缩都在这里）
        self.lbl_status = tk.Label(sidebar, bg=SIDEBAR_BG, fg=TEXT2,
                                   font=(UI_FONT, 9), wraplength=178,
                                   justify="left", anchor="w", text="就绪")
        self.lbl_status.pack(side="bottom", fill="x", padx=16, pady=(0, 10))
        self.pb = ttk.Progressbar(sidebar, mode="determinate", maximum=100)
        self.pb.pack(side="bottom", fill="x", padx=16, pady=(0, 10))
        self.btn_check = RoundedButton(
            sidebar, text="环境自检", width=178, bg="#ffffff", fg=TEXT,
            hover_bg="#f0f0f3", outline=BORDER, command=self.selfcheck)
        self.btn_check.pack(side="bottom", pady=(0, 8))
        self.btn_stop = RoundedButton(
            sidebar, text="停止", width=178, bg="#ffffff", fg=TEXT,
            hover_bg="#f0f0f3", outline=BORDER, state="disabled",
            command=self.stop)
        self.btn_stop.pack(side="bottom", pady=(0, 8))
        self.btn_start = RoundedButton(
            sidebar, text="开始下载", width=178, height=38, bg=ACCENT,
            font=(UI_FONT, 10, "bold"), command=self.start)
        self.btn_start.pack(side="bottom", pady=(0, 10))
        tk.Frame(sidebar, bg=SEP, height=1).pack(side="bottom", fill="x",
                                                 padx=14, pady=(0, 12))

    # -------------------------------------------------- 页面骨架
    def _page_title(self, page, text, sub=None):
        head = tk.Frame(page, bg=BG)
        head.pack(fill="x", padx=20, pady=(18, 4))
        tk.Label(head, text=text, bg=BG, fg=TEXT, anchor="w",
                 font=(UI_FONT, 16, "bold")).pack(anchor="w")
        if sub:
            tk.Label(head, text=sub, bg=BG, fg=TEXT2, anchor="w",
                     font=(UI_FONT, 9)).pack(anchor="w", pady=(2, 0))

    def _card(self, page, title):
        """macOS 风格白底卡片（1px 描边）"""
        outer = tk.Frame(page, bg=BORDER)
        outer.pack(fill="x", padx=20, pady=(12, 0))
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        if title:
            tk.Label(inner, text=title, bg=CARD, fg=TEXT, anchor="w",
                     font=(UI_FONT, 11, "bold")).pack(fill="x", padx=16,
                                                      pady=(12, 6))
        body = tk.Frame(inner, bg=CARD)
        body.pack(fill="x", padx=16, pady=(0, 14))
        return body

    def _show_page(self, key):
        for k, item in self.nav_items.items():
            item.set_selected(k == key)
        self.pages[key].tkraise()
        self.current_page = key
        if key == "files":
            self._refresh_files()

    # -------------------------------------------------- 下载页
    def _page_download(self, page):
        self._page_title(page, "下载", "填好条件后，点左下角的「开始下载」")

        body = self._card(page, "博主账号")
        self.var_accounts = tk.StringVar(value=self.cfg["accounts"])
        ttk.Entry(body, textvariable=self.var_accounts,
                  font=("Consolas", 11)).pack(fill="x")
        tk.Label(body, text="多个账号用逗号或空格分隔，例如：elonmusk, nasa",
                 bg=CARD, fg=TEXT2, anchor="w",
                 font=(UI_FONT, 9)).pack(fill="x", pady=(6, 0))

        body = self._card(page, "下载类型")
        self.var_type = tk.StringVar(value=self.cfg["media_type"])
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        for text, val in (("仅图片", "image"), ("仅视频", "video"),
                          ("图片与视频", "both")):
            ttk.Radiobutton(row, text=text, value=val,
                            variable=self.var_type).pack(side="left",
                                                         padx=(0, 20))
        self.var_gif = tk.BooleanVar(value=self.cfg["gif_as_image"])
        ttk.Checkbutton(body, text="把动图(GIF)算作图片",
                        variable=self.var_gif).pack(anchor="w", pady=(8, 0))

        body = self._card(page, "时间范围")
        self.var_time = tk.StringVar(value=self.cfg["time_mode"])
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        ttk.Radiobutton(row, text="全部时间", value="all",
                        variable=self.var_time,
                        command=self._sync_time).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(row, text="最近", value="days", variable=self.var_time,
                        command=self._sync_time).pack(side="left")
        self.var_days = tk.StringVar(value=self.cfg["days"])
        ttk.Entry(row, textvariable=self.var_days, width=6).pack(side="left",
                                                                 padx=4)
        tk.Label(row, text="天", bg=CARD, fg=TEXT,
                 font=(UI_FONT, 10)).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(row, text="自定义：", value="custom",
                        variable=self.var_time,
                        command=self._sync_time).pack(side="left")
        self.var_from = tk.StringVar(value=self.cfg["date_from"])
        self.var_to = tk.StringVar(value=self.cfg["date_to"])
        self.ent_from = ttk.Entry(row, textvariable=self.var_from, width=12)
        self.ent_from.pack(side="left", padx=4)
        tk.Label(row, text="至", bg=CARD, fg=TEXT,
                 font=(UI_FONT, 10)).pack(side="left")
        self.ent_to = ttk.Entry(row, textvariable=self.var_to, width=12)
        self.ent_to.pack(side="left", padx=4)
        tk.Label(row, text="(YYYY-MM-DD)", bg=CARD, fg=TEXT2,
                 font=(UI_FONT, 9)).pack(side="left")
        self._sync_time()
        self.var_timeline = tk.BooleanVar(value=self.cfg["timeline"])
        ttk.Checkbutton(body, text="时间线模式（含转推/引用，速度较慢）",
                        variable=self.var_timeline).pack(anchor="w", pady=(8, 0))

        body = self._card(page, "保存到")
        self.var_dest = tk.StringVar(value=self.cfg["dest"])
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.var_dest).pack(side="left", fill="x",
                                                        expand=True)
        RoundedButton(row, text="浏览…", width=78, height=30, bg="#ffffff",
                      fg=TEXT, hover_bg="#f0f0f3", outline=BORDER,
                      command=self._pick_dir).pack(side="left", padx=6)
        RoundedButton(row, text="打开", width=66, height=30, bg="#ffffff",
                      fg=TEXT, hover_bg="#f0f0f3", outline=BORDER,
                      command=self._open_dir).pack(side="left")

    # -------------------------------------------------- 高级设置页
    def _page_advanced(self, page):
        self._page_title(page, "高级设置", "代理会自动检测；X 需要登录才能浏览")

        body = self._card(page, "登录 cookies")
        self.var_cookies = tk.StringVar(value=self.cfg["cookies"])
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.var_cookies).pack(side="left", fill="x",
                                                           expand=True)
        RoundedButton(row, text="选择…", width=74, height=30, bg="#ffffff",
                      fg=TEXT, hover_bg="#f0f0f3", outline=BORDER,
                      command=self._pick_cookies).pack(side="left", padx=6)
        row2 = tk.Frame(body, bg=CARD)
        row2.pack(fill="x", pady=(10, 0))
        tk.Label(row2, text="或从浏览器读取：", bg=CARD, fg=TEXT,
                 font=(UI_FONT, 10)).pack(side="left")
        self.var_browser = tk.StringVar(value=self.cfg["browser"])
        ttk.Combobox(row2, textvariable=self.var_browser, width=12,
                     state="readonly",
                     values=["", "chrome", "edge", "firefox", "brave",
                             "opera"]).pack(side="left", padx=6)
        tk.Label(body,
                 text="推荐：浏览器安装扩展 Get cookies.txt LOCALLY，登录 x.com 后导出 cookies.txt",
                 bg=CARD, fg=TEXT2, anchor="w",
                 font=(UI_FONT, 9)).pack(fill="x", pady=(8, 0))

        body = self._card(page, "网络代理")
        self.var_proxy = tk.StringVar(value=self.cfg["proxy"])
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.var_proxy).pack(side="left", fill="x",
                                                          expand=True)
        RoundedButton(row, text="自动检测", width=90, height=30, bg=ACCENT,
                      command=self.detect_proxy).pack(side="left", padx=6)
        tk.Label(body, text="留空即可，会自动尝试 Clash / 系统代理 / 常见端口",
                 bg=CARD, fg=TEXT2, anchor="w",
                 font=(UI_FONT, 9)).pack(fill="x", pady=(8, 0))

        body = self._card(page, "下载选项")
        self.var_sleep = tk.StringVar(value=self.cfg["sleep"])
        self.var_limit = tk.StringVar(value=self.cfg["limit"])
        self.var_resume = tk.BooleanVar(value=self.cfg["resume"])
        self.var_meta = tk.BooleanVar(value=self.cfg["metadata"])
        self.var_preview = tk.BooleanVar(value=self.cfg["preview"])
        grid = tk.Frame(body, bg=CARD)
        grid.pack(fill="x")
        tk.Label(grid, text="每文件间隔(秒)", bg=CARD, fg=TEXT, anchor="w",
                 font=(UI_FONT, 10), width=16).grid(row=0, column=0,
                                                    sticky="w", pady=4)
        ttk.Entry(grid, textvariable=self.var_sleep, width=10).grid(
            row=0, column=1, sticky="w")
        tk.Label(grid, text="最多下载(留空不限)", bg=CARD, fg=TEXT, anchor="w",
                 font=(UI_FONT, 10), width=16).grid(row=1, column=0,
                                                    sticky="w", pady=4)
        ttk.Entry(grid, textvariable=self.var_limit, width=10).grid(
            row=1, column=1, sticky="w")
        right = tk.Frame(grid, bg=CARD)
        right.grid(row=0, column=2, rowspan=2, sticky="w", padx=(28, 0))
        ttk.Checkbutton(right, text="断点续传（跳过已下载）",
                        variable=self.var_resume).pack(anchor="w")
        ttk.Checkbutton(right, text="保存推文信息(.json)",
                        variable=self.var_meta).pack(anchor="w", pady=6)
        ttk.Checkbutton(right, text="下载前先统计数量（显示 x/N）",
                        variable=self.var_preview).pack(anchor="w")

    # -------------------------------------------------- 日志页
    def _page_logs(self, page):
        head = tk.Frame(page, bg=BG)
        head.pack(fill="x", padx=20, pady=(18, 8))
        tk.Label(head, text="运行日志", bg=BG, fg=TEXT, anchor="w",
                 font=(UI_FONT, 16, "bold")).pack(side="left")
        RoundedButton(head, text="清空", width=72, height=30, bg="#ffffff",
                      fg=TEXT, hover_bg="#f0f0f3", outline=BORDER,
                      command=self.clear_log).pack(side="right")
        outer = tk.Frame(page, bg=BORDER)
        outer.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.log_box = scrolledtext.ScrolledText(
            inner, font=("Consolas", 9), bg=CARD, fg=TEXT, relief="flat",
            borderwidth=0, highlightthickness=0, insertbackground=TEXT)
        self.log_box.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_box.tag_config("info", foreground=TEXT)
        self.log_box.tag_config("dim", foreground=TEXT2)
        self.log_box.tag_config("ok", foreground=OK)
        self.log_box.tag_config("warn", foreground=WARN)
        self.log_box.tag_config("error", foreground=ERR)
        self.log_box.tag_config("head", foreground=ACCENT)

    # -------------------------------------------------- 已下载页
    def _page_files(self, page):
        self._page_title(page, "已下载", "查看保存目录里的成果")
        body = self._card(page, "保存目录")
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        self.lbl_dest = tk.Label(row, text=self.cfg["dest"], bg=CARD, fg=TEXT,
                                 anchor="w", font=(UI_FONT, 10))
        self.lbl_dest.pack(side="left", fill="x", expand=True)
        RoundedButton(row, text="刷新", width=70, height=30, bg="#ffffff",
                      fg=TEXT, hover_bg="#f0f0f3", outline=BORDER,
                      command=self._refresh_files).pack(side="left", padx=6)
        RoundedButton(row, text="打开文件夹", width=100, height=30, bg=ACCENT,
                      command=self._open_dir).pack(side="left")

        outer = tk.Frame(page, bg=BORDER)
        outer.pack(fill="both", expand=True, padx=20, pady=(12, 18))
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.files_box = scrolledtext.ScrolledText(
            inner, font=("Consolas", 10), bg=CARD, fg=TEXT, relief="flat",
            borderwidth=0, highlightthickness=0)
        self.files_box.pack(fill="both", expand=True, padx=8, pady=8)

    def _refresh_files(self):
        box = getattr(self, "files_box", None)
        if box is None:
            return
        dest = self.var_dest.get().strip()
        box.delete("1.0", "end")
        try:
            self.lbl_dest.config(text=dest)
        except Exception:  # noqa: BLE001
            pass
        if not os.path.isdir(dest):
            box.insert("end", "目录还不存在，下载后会自动创建：\n" + dest)
            return
        total_n = total_s = 0
        lines = []
        for name in sorted(os.listdir(dest)):
            folder = os.path.join(dest, name)
            if name.startswith(".") or not os.path.isdir(folder):
                continue
            n = s = 0
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.startswith(".") or f.endswith((".sqlite3", ".part")):
                        continue
                    try:
                        s += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
                    n += 1
            total_n += n
            total_s += s
            lines.append("  @%-22s %5d 个   %8.1f MB"
                         % (name, n, s / 1048576.0))
        box.insert("end", "合计：%d 个文件，%.1f MB\n\n"
                   % (total_n, total_s / 1048576.0))
        box.insert("end", "\n".join(lines) if lines else "（还没有下载任何文件）")

    # -------------------------------------------------- 帮助页
    def _page_help(self, page):
        self._page_title(page, "帮助", "常见问题一步到位")
        outer = tk.Frame(page, bg=BORDER)
        outer.pack(fill="both", expand=True, padx=20, pady=(12, 18))
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        box = scrolledtext.ScrolledText(
            inner, font=(UI_FONT, 10), bg=CARD, fg=TEXT, relief="flat",
            borderwidth=0, highlightthickness=0, wrap="word")
        box.pack(fill="both", expand=True, padx=14, pady=12)
        box.tag_config("h", foreground=ACCENT, font=(UI_FONT, 11, "bold"))
        box.insert("end", "开始之前\n", "h")
        box.insert("end",
                   "1. 代理不用填：脚本会自动检测 Clash / 系统代理 / 常见端口。"
                   "启动后看左下角状态，或去「高级设置」点「自动检测」。\n"
                   "2. X 需要登录：装浏览器扩展 Get cookies.txt LOCALLY，"
                   "登录 x.com 后导出 cookies.txt；或在「从浏览器读取」选 chrome / edge（先关掉浏览器）。\n"
                   "3. 点左下角「开始下载」，界面会自动跳到「运行日志」页看进度。\n\n")
        box.insert("end", "各项设置说明\n", "h")
        box.insert("end",
                   "· 下载类型：图片 / 视频 / 两者；动图 GIF 默认算视频，可勾「算作图片」。\n"
                   "· 时间范围：全部 / 最近 N 天 / 自定义起止日期（结束日期含当天）。\n"
                   "· 保存到：每个账号自动建一个子目录，文件名形如 20240101_1234567890_1.jpg。\n"
                   "· 断点续传：已下载文件记在 .archive.sqlite3，再跑一次会自动跳过。\n"
                   "· 最多下载：留空不限；填了就每个账号下这么多为止。\n\n")
        box.insert("end", "出问题怎么办\n", "h")
        box.insert("end",
                   "· 提示需要登录(AuthRequired)：cookies 没设或过期，重新导一次。\n"
                   "· 找到 0 个文件：账号名写错 / 时间范围太窄 / cookies 失效 / 该账号确实没有这类媒体。\n"
                   "· 一直卡着不动：网络不通，点「环境自检」看能不能连上 X。\n"
                   "· 有文件失败：直接再点一次「开始下载」，成功的会自动跳过，只补失败的。\n"
                   "· 完整日志保存在 下载目录/download.log。\n")
        box.configure(state="disabled")

    def _sync_time(self):
        state = "normal" if self.var_time.get() in ("custom",) else "disabled"
        self.ent_from.configure(state=state)
        self.ent_to.configure(state=state)

    # -------------------------------------------------- 小工具
    def _pick_dir(self):
        path = filedialog.askdirectory(initialdir=self.var_dest.get() or BASE_DIR)
        if path:
            self.var_dest.set(path)

    def _open_dir(self):
        path = self.var_dest.get()
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)  # noqa: S606
        except Exception:  # noqa: BLE001
            subprocess.Popen(["explorer", os.path.abspath(path)])

    def _pick_cookies(self):
        path = filedialog.askopenfilename(
            title="选择 cookies.txt", filetypes=[("Cookies", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.var_cookies.set(path)

    # -------------------------------------------------- 日志
    def log(self, msg, tag="info", ts=True):
        """写界面日志（带时间戳），同时写入 download.log"""
        full = f"[{datetime.now():%H:%M:%S}] {msg}" if ts else msg
        self.msg_queue.put((full, tag))
        if self.log_fp:
            try:
                self.log_fp.write(clean(full) + "\n")
                self.log_fp.flush()
            except Exception:  # noqa: BLE001
                pass

    def _drain_queue(self):
        try:
            while True:
                msg, tag = self.msg_queue.get_nowait()
                if tag == "__status__":
                    self.lbl_status.config(text=msg)
                elif tag == "__progress__":
                    self.pb["value"] = msg
                else:
                    self.log_box.insert("end", msg + "\n", tag)
                    self.log_box.see("end")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_queue)

    def clear_log(self):
        self.log_box.delete("1.0", "end")

    def set_status(self, text):
        self.msg_queue.put((text, "__status__"))

    def set_progress(self, pct):
        self.msg_queue.put((max(0, min(100, pct)), "__progress__"))

    def _open_log(self, dest):
        try:
            os.makedirs(dest, exist_ok=True)
            self.log_path = os.path.join(dest, "download.log")
            self.log_fp = open(self.log_path, "a", encoding="utf-8")
            self.log_fp.write(f"\n\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 新任务 =====\n")
        except Exception:  # noqa: BLE001
            self.log_fp = None
            self.log_path = None

    def _close_log(self):
        if self.log_fp:
            try:
                self.log_fp.close()
            except Exception:  # noqa: BLE001
                pass
            self.log_fp = None

    # -------------------------------------------------- 校验
    def _validate(self):
        accounts = [a.strip().lstrip("@").strip("/") for a in
                    re.split(r"[,\s]+", self.var_accounts.get().strip()) if a.strip()]
        if not accounts:
            messagebox.showwarning("缺少信息", "请先填写要下载的博主账号名。")
            return None
        dest = self.var_dest.get().strip()
        if not dest:
            messagebox.showwarning("缺少信息", "请选择保存文件夹。")
            return None

        date_after, date_before = None, None
        mode = self.var_time.get()
        if mode == "days":
            try:
                days = max(1, int(self.var_days.get().strip() or 30))
            except ValueError:
                messagebox.showwarning("格式错误", "“最近天数”必须是整数。")
                return None
            date_after = date.today() - timedelta(days=days)
        elif mode == "custom":
            date_after = parse_date(self.var_from.get())
            date_before = parse_date(self.var_to.get())
            if not date_after and not date_before:
                messagebox.showwarning("格式错误",
                                       "请填写日期，格式如 2024-01-01。")
                return None
            if date_after and date_before and date_after > date_before:
                messagebox.showwarning("格式错误", "开始日期不能晚于结束日期。")
                return None
            if date_before:  # 结束日期包含当天
                date_before = date_before + timedelta(days=1)

        limit = None
        if self.var_limit.get().strip():
            try:
                limit = max(1, int(self.var_limit.get().strip()))
            except ValueError:
                messagebox.showwarning("格式错误", "“最多下载”必须是整数。")
                return None

        try:
            sleep = max(0.0, float(self.var_sleep.get().strip() or 0))
        except ValueError:
            sleep = 0.0

        return {
            "accounts": accounts,
            "media_type": self.var_type.get(),
            "date_after": date_after,
            "date_before": date_before,
            "dest": dest,
            "limit": limit,
            "sleep": sleep,
            "cookies": self.var_cookies.get().strip(),
            "browser": self.var_browser.get().strip(),
            "proxy": self.var_proxy.get().strip(),
            "resume": self.var_resume.get(),
            "gif_as_image": self.var_gif.get(),
            "timeline": self.var_timeline.get(),
            "metadata": self.var_meta.get(),
        }

    # -------------------------------------------------- 下载
    def start(self):
        if self.running:
            return
        opts = self._validate()
        if not opts:
            return
        self._save_config()
        self._show_page("logs")      # 开跑后自动切到日志页看进度

        base = build_base_command()
        if base is None:
            self.log("未检测到 gallery-dl，准备自动安装…", "warn")
            self.btn_start.configure(state="disabled")
            threading.Thread(target=self._install_then_run,
                             args=(opts,), daemon=True).start()
        else:
            self._run(opts)

    def _install_then_run(self, opts):
        ok = install_gallery_dl(self.log)
        self.root.after(0, lambda: self.btn_start.configure(state="normal"))
        if ok:
            self.root.after(0, lambda: self._run(opts))
        else:
            self.log("安装失败，请手动执行：pip install -U gallery-dl", "error")

    def _run(self, opts):
        base = build_base_command()
        if base is None:
            self.log("仍然找不到 gallery-dl，请手动安装后重试。", "error")
            return
        self.running = True
        self.stop_flag.clear()
        self.total_downloaded = 0
        self.file_errors = 0
        self.auth_needed = False
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        threading.Thread(target=self._worker, args=(base, opts), daemon=True).start()

    def stop(self):
        self.stop_flag.set()
        self.log("正在停止，请稍候…", "warn")
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass

    def _build_cmd(self, base, opts, user, user_dir):
        cmd = list(base)
        cmd += ["-d", user_dir]
        cmd += ["--filename", "{date:%Y%m%d}_{id}_{num}.{extension}"]
        cmd += ["--retries", "10", "--http-timeout", "30", "--no-colors"]
        if opts["sleep"] > 0:
            cmd += ["--sleep", str(opts["sleep"])]
        if opts["resume"]:
            cmd += ["--download-archive",
                    os.path.join(user_dir, ".archive.sqlite3")]
        if opts["metadata"]:
            cmd += ["--write-metadata"]

        ftype = opts["media_type"]
        if ftype == "image" and opts["gif_as_image"]:
            expr = "locals().get('type') in ('photo', 'animated_gif')"
        else:
            expr = TYPE_FILTER[ftype]
        if expr:
            cmd += ["--filter", expr]

        if opts["date_after"]:
            cmd += ["--date-after", opts["date_after"].strftime("%Y-%m-%d")]
        if opts["date_before"]:
            cmd += ["--date-before", opts["date_before"].strftime("%Y-%m-%d")]

        if opts["cookies"] and os.path.isfile(opts["cookies"]):
            cmd += ["--cookies", opts["cookies"]]
        elif opts["browser"]:
            cmd += ["--cookies-from-browser", opts["browser"]]

        if opts["proxy"]:
            cmd += ["--proxy", opts["proxy"]]

        url = f"https://x.com/{user}" if opts["timeline"] else f"https://x.com/{user}/media"
        cmd.append(url)
        return cmd, url

    def _worker(self, base, opts):
        started = datetime.now()
        self.file_errors = 0
        self._open_log(opts["dest"])
        self.set_status("正在准备…")
        self.set_progress(0)

        # ---- 任务摘要，让用户先确认参数对不对
        self.log("=" * 66, "head", ts=False)
        self.log("任务开始", "head")
        self.log(f"账号   ：{'  '.join('@' + a for a in opts['accounts'])}")
        tlabel = TYPE_LABEL[opts["media_type"]]
        if opts["media_type"] == "image" and opts["gif_as_image"]:
            tlabel += "（含动图 GIF）"
        self.log(f"类型   ：{tlabel}")
        if opts["date_after"] or opts["date_before"]:
            end = (opts["date_before"] - timedelta(days=1)).strftime("%Y-%m-%d") \
                if opts["date_before"] else "不限"
            start = opts["date_after"].strftime("%Y-%m-%d") if opts["date_after"] else "不限"
            self.log(f"时间   ：{start}  ~  {end}")
        else:
            self.log("时间   ：全部")
        self.log(f"保存   ：{opts['dest']}  （每个账号一个子目录）")
        self.log(f"模式   ：{'时间线（含转推/引用）' if opts['timeline'] else '媒体页（该账号自己的媒体）'}")
        self.log(f"代理   ：{opts['proxy'] or '自动检测中，结果见下'}")
        if opts["cookies"]:
            self.log(f"登录   ：cookies 文件 {opts['cookies']}"
                     f"{'' if os.path.isfile(opts['cookies']) else '  ← 文件不存在！'}")
        elif opts["browser"]:
            self.log(f"登录   ：从浏览器 {opts['browser']} 读取 cookies")
        else:
            self.log("登录   ：未设置 cookies（X 需登录，可能什么都抓不到）", "warn")
        if opts["limit"]:
            self.log(f"上限   ：每个账号最多 {opts['limit']} 个文件")
        self.log("=" * 66, "head", ts=False)

        # ---- 没填代理就自动找（Clash / 系统代理 / 常见端口）
        if not opts["proxy"]:
            self.set_status("正在自动检测代理…")
            self.log("未填写代理，开始自动检测…", "dim")
            found, source = auto_detect_proxy(logger=self.log)
            if found is None:
                self.log(f"自动检测失败：{source}。下面仍会尝试直连，很可能失败。", "warn")
                opts["proxy"] = ""
            else:
                opts["proxy"] = found
                self.root.after(0, lambda: self.var_proxy.set(found))
                self.log(f"✔ 使用代理：{found or '直连'}（{source}）", "ok")
        self.log(f"联网方式：{opts['proxy'] or '直连'}", "dim")

        n = len(opts["accounts"])
        try:
            for idx, user in enumerate(opts["accounts"], 1):
                if self.stop_flag.is_set():
                    break
                user_dir = os.path.join(opts["dest"], self._safe(user))
                os.makedirs(user_dir, exist_ok=True)
                self.log(f"\n----- [{idx}/{n}] 开始处理 @{user} -----", "head")

                # 步骤 1：统计数量
                total = None
                if self.var_preview.get():
                    self.set_status(f"[{idx}/{n}] @{user}：正在统计文件数量…")
                    total = self._preview(base, opts, user, user_dir)
                    if total == 0:
                        self.log("  没有找到符合条件的文件，跳过该账号。"
                                 " 常见原因：账号名错误 / 无 cookies 或已过期 / 代理不通 / 时间范围太窄。",
                                 "warn")
                        continue
                    if self.stop_flag.is_set():
                        break

                # 步骤 2：下载
                cmd, url = self._build_cmd(base, opts, user, user_dir)
                self.set_status(f"[{idx}/{n}] @{user}：正在下载…")
                self.log(f"  地址：{url}", "dim")
                self.log("  命令：" + " ".join(f'"{c}"' if " " in c else c for c in cmd), "dim")
                got = self._run_one(cmd, user_dir, opts["limit"], total, user)

                # 步骤 3：小结
                have = self._count_files(user_dir)
                self.log(f"  完成 @{user}：本次处理 {got} 个文件，目录内现有 {have} 个文件"
                         + (f"（预计 {total} 个）" if total else ""),
                         "ok" if got or have else "warn")
                if got == 0 and have == 0:
                    self.log("  ⚠ 一个文件都没下载到，建议先点「环境自检」排查网络/登录问题。", "error")
        except Exception:  # noqa: BLE001
            self.log("发生异常：\n" + traceback.format_exc(), "error")
        finally:
            cost = max(1, int((datetime.now() - started).total_seconds()))
            self.set_progress(100)
            self.log("\n" + "=" * 66, "head", ts=False)
            if self.stop_flag.is_set():
                self.log(f"已手动停止：累计处理 {self.total_downloaded} 个文件，耗时 {cost} 秒", "warn")
            else:
                self.log(f"任务结束：累计处理 {self.total_downloaded} 个文件，耗时 {cost} 秒", "ok")
            if self.file_errors:
                self.log(f"其中 {self.file_errors} 个文件下载失败（上方红色行），"
                         f"可再次点击「开始下载」，已下载的文件会自动跳过。", "warn")
            if getattr(self, "auth_needed", False):
                self.log("X 返回「需要登录」：请在「高级选项」里设置 cookies —— 用浏览器扩展 "
                         "「Get cookies.txt LOCALLY」登录 x.com 后导出 cookies.txt，"
                         "或在「从浏览器读取」里选 chrome / edge，然后重新下载。", "error")
            self.log(f"保存位置：{opts['dest']}", "head")
            if self.log_path:
                self.log(f"完整日志：{self.log_path}", "dim")
            self.log("=" * 66, "head", ts=False)
            self._close_log()
            self.root.after(0, self._finish)

    def _preview(self, base, opts, user, user_dir):
        """用 --no-download 先扫一遍，统计有多少个符合条件的文件"""
        cmd, url = self._build_cmd(base, opts, user, user_dir)
        cmd.insert(len(base), "--no-download")
        if "--download-archive" in cmd:      # 预扫不要写归档
            i = cmd.index("--download-archive")
            del cmd[i:i + 2]
        self.log(f"  [1/2] 统计 @{user} 的媒体数量（不下载，最多等 {PREVIEW_TIMEOUT} 秒）…", "dim")
        count, t0 = 0, time.time()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                startupinfo=_startup_info(), env=_child_env())
        except Exception as exc:  # noqa: BLE001
            self.log(f"  统计失败：{exc}", "warn")
            return None
        for raw in proc.stdout:
            line = clean(raw)
            if user_dir in line and os.sep in line:
                count += 1
            if line and ("[error]" in line.lower() or "[warning]" in line.lower()):
                self.log("  " + line, "warn")
            if self.stop_flag.is_set() or time.time() - t0 > PREVIEW_TIMEOUT:
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                self.log("  统计超时/被中断，直接开始下载（进度条将不显示总数）。", "warn")
                return None
        proc.wait()
        if count:
            self.log(f"  [1/2] 共发现 {count} 个符合条件的文件", "ok")
        return count

    def _run_one(self, cmd, user_dir, limit, total=None, user=""):
        self.log(f"  [2/2] 开始下载" + (f"（共 {total} 个）" if total else ""), "ok")
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                startupinfo=_startup_info(), env=_child_env())
        except FileNotFoundError:
            self.log("  无法启动 gallery-dl，请检查安装。", "error")
            return 0

        downloaded = 0
        for raw in self.proc.stdout:
            line = clean(raw)
            if not line:
                continue
            low = line.lower()
            tag = "dim"
            if "[error]" in low or "http error" in low or "unable to download" in low:
                tag = "error"
                self.file_errors += 1
                if "authrequired" in low or "authenticated cookies needed" in low \
                        or "an account is required" in low:
                    self.auth_needed = True
            elif "[warning]" in low or "unable to" in low:
                tag = "warn"
            elif "[info]" in low or "[debug]" in low:
                tag = "dim"
            elif user_dir in line or line.startswith("#"):
                tag = "info"

            if user_dir in line and os.sep in line:
                downloaded += 1
                self.total_downloaded += 1
                if total:
                    self.set_progress(int(downloaded * 100 / total))
                self.set_status(
                    f"@{user}：{downloaded}/{total or '?'} 个"
                    f"（累计 {self.total_downloaded}）"
                    f"{' · 失败 ' + str(self.file_errors) if self.file_errors else ''}")
            self.log("  " + line, tag)

            if limit and downloaded >= limit:
                self.log(f"  已达到数量上限 {limit}，停止该账号。", "warn")
                try:
                    self.proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                break
        self.proc.wait()
        return downloaded

    @staticmethod
    def _count_files(folder: str) -> int:
        n = 0
        for _, _, files in os.walk(folder):
            for f in files:
                if f.startswith(".") or f.endswith((".json", ".sqlite3", ".part")):
                    continue
                n += 1
        return n

    # -------------------------------------------------- 代理自动检测
    def detect_proxy(self):
        if getattr(self, "_detecting", False):
            return
        self._detecting = True
        self.set_status("正在自动检测代理…")
        self.log("自动检测代理：依次尝试 直连 / 系统代理 / Clash 配置端口 / 常见端口 …", "dim")
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self):
        proxy, source = auto_detect_proxy(logger=self.log)
        self._detecting = False
        if proxy is None:
            self.log(f"自动检测失败：{source}", "error")
            self.log("请确认 Clash 已启动并能访问 X；或在「代理」框里手动填写，"
                     "如 http://127.0.0.1:7890（Clash）或 http://127.0.0.1:7897（Clash Verge）。",
                     "warn")
            self.set_status("未检测到可用代理")
            self.detected_proxy = None
            return
        self.detected_proxy = proxy
        self.root.after(0, lambda: self.var_proxy.set(proxy))
        if proxy:
            self.log(f"✔ 已找到代理：{proxy}（{source}）", "ok")
            self.set_status(f"代理已就绪：{proxy}")
        else:
            self.log(f"✔ {source}，无需代理", "ok")
            self.set_status("直连可用，无需代理")
        self._save_config()

    # -------------------------------------------------- 环境自检
    def selfcheck(self):
        if self.running:
            return
        self.btn_check.configure(state="disabled")
        threading.Thread(target=self._selfcheck, daemon=True).start()

    def _selfcheck(self):
        self.log("\n----- 环境自检 -----", "head", ts=False)
        self.log(f"程序版本  ：{APP_NAME} v{APP_VERSION}"
                 f"（{'桌面版 · 引擎内置' if IS_FROZEN else '源码版'}）")
        self.log(f"运行环境  ：{sys.executable}  ({sys.version.split()[0]})")

        base = build_base_command()
        if base is None:
            self.log("gallery-dl：未安装（点「开始下载」会自动安装）", "warn")
        else:
            try:
                out = subprocess.run(base + ["--version"], capture_output=True,
                                     text=True, timeout=30,
                                     startupinfo=_startup_info(), env=_child_env())
                ver = clean((out.stdout or "") + (out.stderr or "")).strip()
                self.log(f"gallery-dl：{ver or '已安装'}", "ok")
            except Exception as exc:  # noqa: BLE001
                self.log(f"gallery-dl：获取版本失败 {exc}", "error")

        cookies = self.var_cookies.get().strip()
        browser = self.var_browser.get().strip()
        if cookies:
            self.log(f"Cookies   ：{cookies} —— "
                     f"{'文件存在' if os.path.isfile(cookies) else '文件不存在，请重新选择！'}",
                     "ok" if os.path.isfile(cookies) else "error")
        elif browser:
            self.log(f"Cookies   ：将从浏览器 {browser} 读取（建议先关闭该浏览器）", "warn")
        else:
            self.log("Cookies   ：未设置 —— X 需要登录才能浏览，建议设置后再下载", "warn")

        dest = self.var_dest.get().strip()
        try:
            os.makedirs(dest, exist_ok=True)
            probe = os.path.join(dest, ".write_test")
            with open(probe, "w", encoding="utf-8") as fp:
                fp.write("ok")
            os.remove(probe)
            self.log(f"保存目录  ：{dest} —— 可写", "ok")
        except Exception as exc:  # noqa: BLE001
            self.log(f"保存目录  ：{dest} —— 不可写！{exc}", "error")

        proxy = self.var_proxy.get().strip()
        if not proxy:
            self.log("代理      ：未填写，开始自动检测…", "dim")
            found, source = auto_detect_proxy(logger=self.log)
            if found is None:
                self.log(f"自动检测失败：{source}", "error")
            else:
                proxy = found
                self.root.after(0, lambda: self.var_proxy.set(found))
                self.log(f"已找到代理：{found or '直连'}（{source}）", "ok")
        self.log(f"代理      ：{proxy or '直连'}；正在测试能否连上 X（最多 25 秒）…", "dim")
        ok, detail = self._test_connect(proxy)
        if ok:
            self.log(f"网络连通  ：成功 —— {detail}", "ok")
            self.log("可以到「开始下载」了；若仍下载不到文件，多半是 cookies 失效。", "ok")
        else:
            self.log(f"网络连通  ：失败 —— {detail}", "error")
            self.log("请确认 Clash 已启动、规则允许访问 X（可在 Clash 里把 X 相关域名加入代理规则），"
                     "再点「自动检测」。", "error")
        self.root.after(0, lambda: self.btn_check.configure(state="normal"))

    @staticmethod
    def _test_connect(proxy: str, timeout: int = 25):
        """复用 http_probe：收到任何 HTTP 响应都算通（x.com 首页常被 Clash 特殊处理）"""
        return http_probe(proxy, timeout)

    def _finish(self):
        self.running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        have = self._count_files(self.var_dest.get().strip())
        self.set_status(f"完成：目录内共 {have} 个文件"
                        + (f"，本次处理 {self.total_downloaded} 个" if self.total_downloaded else ""))
        if not self.stop_flag.is_set():
            messagebox.showinfo(
                "下载结束",
                f"本次处理 {self.total_downloaded} 个文件，目录内现有 {have} 个文件。\n"
                f"保存位置：{self.var_dest.get()}\n"
                "详细过程请看主界面日志。")

    @staticmethod
    def _safe(name: str) -> str:
        return re.sub(r'[\\/:*?"<>|]+', "_", name) or "unknown"

    def on_close(self):
        self._save_config()
        if self.running and not messagebox.askokcancel(
                "退出", "下载正在进行中，确定要退出吗？"):
            return
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
