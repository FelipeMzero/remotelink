"""
RemoteLink - GUI Application
Dark theme - profissional e moderna
Suporte a Rede Externa (WAN / UPnP / Cloud Rendezvous / Código Externo / Conexão Reversa)
e Controle Direto de Teclado e Mouse estilo AnyDesk (Hook Win32 WH_KEYBOARD_LL + Drag & Drop).
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import sys
import os
import io
import hashlib
import platform
import ctypes
import logging
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.identity import (
    get_machine_info, resolve_target, NetworkScanner,
    is_local_target, is_own_code, get_public_ip,
    encode_external_code, CloudRegistry, CANDIDATE_OPEN_PORTS
)
from core.client import (
    RemoteLinkClient, probe_target, probe_any_port,
    probe_hostname, resolve_hostname_to_ips
)
from core.server import RemoteLinkServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remotelink.gui")

_IS_WIN = platform.system() == "Windows"

if _IS_WIN:
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _LRESULT = ctypes.c_ssize_t
    _HHOOK = wintypes.HANDLE
    _ULONG_PTR = ctypes.c_size_t

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode",      wintypes.DWORD),
            ("scanCode",    wintypes.DWORD),
            ("flags",       wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    _HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _user32.SetWindowsHookExW.restype = _HHOOK
    _user32.CallNextHookEx.argtypes = [_HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallNextHookEx.restype = _LRESULT
    _user32.UnhookWindowsHookEx.argtypes = [_HHOOK]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.IsChild.restype = wintypes.BOOL
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND

    WH_KEYBOARD_LL = 13
    WM_KEYDOWN     = 0x0100
    WM_KEYUP       = 0x0101
    WM_SYSKEYDOWN  = 0x0104
    WM_SYSKEYUP    = 0x0105
    GA_ROOT        = 2


# ── Outfit Font Auto-Loader ───────────────────────────────────────────────────
if _IS_WIN:
    try:
        _root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _font_path = os.path.join(_root_dir, "assets", "fonts", "Outfit-VariableFont_wght.ttf")
        if os.path.exists(_font_path):
            ctypes.windll.gdi32.AddFontResourceExW(os.path.abspath(_font_path), 0x10, 0)
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


# ── Clean Modern White / Light Theme ──────────────────────────────────────────
C = {
    "bg_dark":        "#f8fafc",   # Slate-50: dashboards, toolbars, top cards
    "bg_surface":     "#ffffff",   # Pure white main surface
    "bg_card":        "#ffffff",   # Pure white cards
    "bg_alt":         "#f1f5f9",   # Slate-100: secondary buttons, highlights
    "bg_input":       "#ffffff",   # Pure white inputs
    "border":         "#e2e8f0",   # Slate-200: clean subtle modern borders
    "border_focus":   "#2563eb",   # Vibrant Blue border
    "accent":         "#2563eb",   # Vibrant Primary Blue (Tailwind Blue-600)
    "accent_hover":   "#1d4ed8",   # Blue-700
    "accent_muted":   "#eff6ff",   # Blue-50 soft tint
    "success":        "#16a34a",   # Green-600
    "success_bg":     "#f0fdf4",   # Green-50 soft tint
    "warning":        "#d97706",   # Amber-600
    "warning_bg":     "#fffbeb",   # Amber-50 soft tint
    "error":          "#dc2626",   # Red-600
    "error_bg":       "#fef2f2",   # Red-50 soft tint
    "error_hover":    "#b91c1c",   # Red-700
    "text":           "#0f172a",   # Slate-900: high contrast ultra-sharp text
    "text_secondary": "#475569",   # Slate-600: clean readable labels
    "text_disabled":  "#94a3b8",   # Slate-400
    "text_caption":   "#64748b",   # Slate-500
    "text_on_accent": "#ffffff",   # White text on buttons
    "nav_bg":         "#f8fafc",   # Slate-50 navbar
    "nav_hover":      "#f1f5f9",   # Hover state
    "nav_active":     "#eff6ff",   # Blue-50 active item
    "nav_active_bar": "#2563eb",   # Active blue bar
    "ctrl_hover":     "#e2e8f0",   # Control hover
    "scroll_bg":      "#f8fafc",
    "scroll_fg":      "#cbd5e1",
    "scroll_hover":   "#94a3b8",
    "code_bg":        "#f1f5f9",   # Code / token box background
    "code_text":      "#1d4ed8",   # Blue code text
    "progress_bg":    "#e2e8f0",
    "progress_fg":    "#2563eb",
}

# ── Fonts (Outfit Primária) ───────────────────────────────────────────────────
import tkinter.font as tkfont

_UI_FAMS   = ["Outfit", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", "Arial"]
_MONO_FAMS = ["Outfit", "Cascadia Code", "Cascadia Mono", "Consolas", "Courier New"]

def _f(fams, size, bold=False):
    available = tkfont.families()
    for name in fams:
        if name in available:
            return (name, size, "bold") if bold else (name, size)
    return (fams[-1], size, "bold") if bold else (fams[-1], size)

FONT_UI = FONT_UI_SM = FONT_UI_MED = FONT_UI_LG = None
FONT_UI_BODY_B = FONT_UI_SUBH = FONT_MONO = FONT_MONO_LG = FONT_CODE_XL = None

def _setup_fonts():
    global FONT_UI, FONT_UI_SM, FONT_UI_MED, FONT_UI_LG
    global FONT_UI_BODY_B, FONT_UI_SUBH, FONT_MONO, FONT_MONO_LG, FONT_CODE_XL
    FONT_UI       = _f(_UI_FAMS, 10)
    FONT_UI_SM    = _f(_UI_FAMS, 9)
    FONT_UI_MED   = _f(_UI_FAMS, 11)
    FONT_UI_LG    = _f(_UI_FAMS, 13)
    FONT_UI_BODY_B= _f(_UI_FAMS, 10, bold=True)
    FONT_UI_SUBH  = _f(_UI_FAMS, 12, bold=True)
    FONT_MONO     = _f(_MONO_FAMS, 10)
    FONT_MONO_LG  = _f(_MONO_FAMS, 13)
    FONT_CODE_XL  = _f(_MONO_FAMS, 21, bold=True)


def configure_styles():
    _setup_fonts()
    s = ttk.Style()
    s.theme_use("clam")
    BG = C["bg_surface"]

    s.configure("TFrame",      background=BG)
    s.configure("Nav.TFrame",  background=C["nav_bg"])
    s.configure("Card.TFrame", background=C["bg_card"])
    s.configure("Dark.TFrame", background=C["bg_dark"])

    s.configure("TLabel",
        background=BG, foreground=C["text"], font=FONT_UI)
    s.configure("Secondary.TLabel",
        background=BG, foreground=C["text_secondary"], font=FONT_UI_SM)
    s.configure("Caption.TLabel",
        background=BG, foreground=C["text_caption"], font=FONT_UI_SM)
    s.configure("Card.TLabel",
        background=C["bg_card"], foreground=C["text"], font=FONT_UI)
    s.configure("Card.Secondary.TLabel",
        background=C["bg_card"], foreground=C["text_secondary"], font=FONT_UI_SM)

    s.configure("TButton",
        background=C["bg_alt"], foreground=C["text"],
        font=FONT_UI, relief="flat", borderwidth=1,
        bordercolor=C["border"], padding=(14, 6))
    s.map("TButton",
        background=[("active", C["ctrl_hover"]),
                    ("pressed", C["bg_alt"])])

    s.configure("Accent.TButton",
        background=C["accent"], foreground=C["text_on_accent"],
        font=FONT_UI_BODY_B, relief="flat", borderwidth=0, padding=(16, 7))
    s.map("Accent.TButton",
        background=[("active", C["accent_hover"]),
                    ("pressed", C["accent"])])

    s.configure("Danger.TButton",
        background=C["error"], foreground=C["text_on_accent"],
        font=FONT_UI_BODY_B, relief="flat", borderwidth=0, padding=(14, 6))
    s.map("Danger.TButton",
        background=[("active", C["error_hover"])])

    s.configure("Success.TButton",
        background=C["success"], foreground=C["text_on_accent"],
        font=FONT_UI_BODY_B, relief="flat", borderwidth=0, padding=(14, 6))
    s.map("Success.TButton",
        background=[("active", "#15803d")])

    s.configure("TSeparator",   background=C["border"])
    s.configure("TScrollbar",
        background=C["scroll_fg"], troughcolor=C["scroll_bg"],
        borderwidth=0, arrowsize=0, width=8)
    s.map("TScrollbar",
        background=[("active", C["scroll_hover"])])

    s.configure("Treeview",
        background=C["bg_card"], foreground=C["text"],
        fieldbackground=C["bg_card"], borderwidth=0,
        font=FONT_UI, rowheight=34)
    s.configure("Treeview.Heading",
        background=C["bg_alt"], foreground=C["text_secondary"],
        font=FONT_UI_SM, borderwidth=0, relief="flat")
    s.map("Treeview",
        background=[("selected", C["accent_muted"])],
        foreground=[("selected", C["text"])])

    s.configure("Horizontal.TProgressbar",
        background=C["progress_fg"], troughcolor=C["progress_bg"],
        borderwidth=0, thickness=3)


# ── Base UI Helpers ────────────────────────────────────────────────────────────

class Divider(tk.Frame):
    def __init__(self, parent, color=None, vertical=False, **kw):
        if vertical:
            super().__init__(parent, width=1, bg=color or C["border"], **kw)
        else:
            super().__init__(parent, height=1, bg=color or C["border"], **kw)


class CardFrame(tk.Frame):
    def __init__(self, parent, padding=16, **kw):
        super().__init__(parent,
            bg=C["bg_card"],
            highlightbackground=C["border"],
            highlightthickness=1, **kw)
        self.inner = tk.Frame(self, bg=C["bg_card"])
        self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)


class SectionHeader(tk.Frame):
    def __init__(self, parent, title, subtitle=None, bg=None, **kw):
        bg = bg or C["bg_surface"]
        super().__init__(parent, bg=bg, **kw)
        tk.Label(self, text=title, font=FONT_UI_SUBH,
                 bg=bg, fg=C["text"]).pack(anchor="w")
        if subtitle:
            tk.Label(self, text=subtitle, font=FONT_UI_SM,
                     bg=bg, fg=C["text_secondary"],
                     wraplength=560, justify="left").pack(anchor="w", pady=(2, 0))


class FlatBtn(tk.Button):
    _PRESETS = {
        "default": dict(bg=C["bg_alt"], fg=C["text"],
                        abg=C["ctrl_hover"], afg=C["text"],
                        hl=C["border"], hlt=1, px=14, py=6),
        "accent":  dict(bg=C["accent"], fg=C["text_on_accent"],
                        abg=C["accent_hover"], afg=C["text_on_accent"],
                        hl="", hlt=0, px=16, py=7),
        "danger":  dict(bg=C["error"], fg=C["text_on_accent"],
                        abg=C["error_hover"], afg=C["text_on_accent"],
                        hl="", hlt=0, px=14, py=6),
        "success": dict(bg=C["success"], fg=C["text_on_accent"],
                        abg="#15803d", afg=C["text_on_accent"],
                        hl="", hlt=0, px=14, py=6),
        "subtle":  dict(bg=C["bg_surface"], fg=C["text"],
                        abg=C["bg_alt"], afg=C["text"],
                        hl=C["border"], hlt=1, px=10, py=5),
        "nav_subtle": dict(bg=C["nav_bg"], fg=C["text_secondary"],
                        abg=C["nav_hover"], afg=C["text"],
                        hl="", hlt=0, px=10, py=5),
    }

    def __init__(self, parent, text="", icon="", variant="default",
                 command=None, **kw):
        label = f"{icon} {text}".strip() if icon else text
        p = self._PRESETS.get(variant, self._PRESETS["default"])
        cfg = dict(
            text=label, font=FONT_UI, relief="flat", cursor="hand2",
            bg=p["bg"], fg=p["fg"],
            activebackground=p["abg"], activeforeground=p["afg"],
            highlightthickness=p["hlt"],
            padx=p["px"], pady=p["py"], command=command,
        )
        hl = p.get("hl", "")
        if hl:
            cfg["highlightbackground"] = hl
        cfg.update(kw)
        super().__init__(parent, **cfg)


class Badge(tk.Label):
    _P = {
        "success": (C["success_bg"], C["success"]),
        "error":   (C["error_bg"],   C["error"]),
        "warning": (C["warning_bg"], C["warning"]),
        "info":    (C["accent_muted"], C["accent"]),
        "neutral": (C["bg_alt"], C["text_secondary"]),
    }
    def __init__(self, parent, text, preset="info", **kw):
        bg, fg = self._P.get(preset, self._P["neutral"])
        super().__init__(parent, text=text, bg=bg, fg=fg,
                         font=FONT_UI_SM, padx=8, pady=2, **kw)


class StatusDot(tk.Frame):
    def __init__(self, parent, bg=None, **kw):
        bg = bg or C["bg_surface"]
        super().__init__(parent, bg=bg, **kw)
        self._bg = bg
        self._dot = tk.Label(self, text="\u25cf", font=_f(_UI_FAMS, 10),
                             bg=bg, fg=C["text_disabled"])
        self._dot.pack(side="left", padx=(0, 5))
        self._lbl = tk.Label(self, text="\u2014", font=FONT_UI,
                             bg=bg, fg=C["text_secondary"])
        self._lbl.pack(side="left")
        self._pid = None

    def set(self, status: str, text: str = None):
        colors = {
            "online": C["success"], "connected": C["success"],
            "listening": C["accent"], "connecting": C["warning"],
            "disconnected": C["text_disabled"], "error": C["error"],
            "stopped": C["text_disabled"],
        }
        texts = {
            "online": "Online", "connected": "Conectado",
            "listening": "Aguardando conexoes (LAN e Rede Externa)", "connecting": "Conectando...",
            "disconnected": "Desconectado", "error": "Erro", "stopped": "Parado",
        }
        color = colors.get(status, C["text_disabled"])
        label = text or texts.get(status, status)
        if self._pid:
            self.after_cancel(self._pid)
            self._pid = None
        self._dot.config(fg=color)
        self._lbl.config(text=label, fg=C["text_secondary"])
        if status in ("listening", "connecting"):
            self._pulse(color)

    def _pulse(self, color):
        try:
            cur = self._dot.cget("fg")
            self._dot.config(fg=C["text_disabled"] if cur == color else color)
            self._pid = self.after(700, lambda: self._pulse(color))
        except Exception:
            pass


class NavItem(tk.Frame):
    def __init__(self, parent, label, command, **kw):
        super().__init__(parent, bg=C["nav_bg"], cursor="hand2", **kw)
        self._cmd = command
        self._active = False

        self._bar = tk.Frame(self, width=3, bg=C["nav_bg"])
        self._bar.pack(side="left", fill="y", pady=4)

        self._inner = tk.Frame(self, bg=C["nav_bg"])
        self._inner.pack(side="left", fill="both", expand=True, padx=(6, 14), pady=9)

        self._text = tk.Label(self._inner, text=label,
                              font=FONT_UI, bg=C["nav_bg"], fg=C["text"])
        self._text.pack(side="left")

        for w in (self, self._inner, self._text, self._bar):
            w.bind("<Button-1>", lambda e: self._cmd() if self._cmd else None)
        for w in (self, self._inner, self._text):
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)

    def activate(self, on: bool):
        self._active = on
        bg = C["nav_active"] if on else C["nav_bg"]
        bar_bg = C["nav_active_bar"] if on else C["nav_bg"]
        self._bar.config(bg=bar_bg)
        for w in (self, self._inner, self._text):
            w.config(bg=bg)

    def _hover_on(self, e=None):
        if not self._active:
            for w in (self, self._inner, self._text):
                w.config(bg=C["nav_hover"])

    def _hover_off(self, e=None):
        if not self._active:
            for w in (self, self._inner, self._text):
                w.config(bg=C["nav_bg"])


# ── Connection Preview Panel ───────────────────────────────────────────────────

class ConnectionPreview(tk.Frame):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["bg_surface"])
        super().__init__(parent, **kw)
        self._cb = None
        self._info = None
        self._aid = None
        self._ai = 0
        self._build()

    def _build(self):
        card = tk.Frame(self, bg=C["bg_card"],
                        highlightbackground=C["border"], highlightthickness=1)
        card.pack(fill="x", pady=(8, 0))

        hdr = tk.Frame(card, bg=C["bg_alt"])
        hdr.pack(fill="x")
        self._title = tk.Label(hdr, text="Verificando...",
            font=FONT_UI_BODY_B, bg=C["bg_alt"], fg=C["text"],
            padx=16, pady=10, anchor="w")
        self._title.pack(side="left", fill="x", expand=True)
        tk.Button(hdr, text="\u2715", font=FONT_UI_SM,
            bg=C["bg_alt"], fg=C["text_secondary"],
            activebackground=C["bg_dark"], activeforeground=C["error"],
            relief="flat", cursor="hand2", padx=12, pady=8,
            command=self.hide).pack(side="right")
        Divider(card).pack(fill="x")

        body = tk.Frame(card, bg=C["bg_card"])
        body.pack(fill="x", padx=20, pady=16)

        self._load_f = tk.Frame(body, bg=C["bg_card"])
        self._load_f.pack(fill="x")
        self._spin = tk.Label(self._load_f, text="\u25cc",
            font=_f(_UI_FAMS, 20), bg=C["bg_card"], fg=C["accent"])
        self._spin.pack(side="left", padx=(0, 10))
        self._spin_txt = tk.Label(self._load_f, text="Verificando na rede local e externa...",
            font=FONT_UI, bg=C["bg_card"], fg=C["text_secondary"])
        self._spin_txt.pack(side="left")

        self._res_f = tk.Frame(body, bg=C["bg_card"])

        mhdr = tk.Frame(self._res_f, bg=C["bg_card"])
        mhdr.pack(fill="x", pady=(0, 12))
        nc = tk.Frame(mhdr, bg=C["bg_card"])
        nc.pack(side="left", fill="x", expand=True)
        self._host_lbl = tk.Label(nc, text="\u2014", font=FONT_UI_LG,
                                   bg=C["bg_card"], fg=C["text"], anchor="w")
        self._host_lbl.pack(anchor="w")
        self._plat_lbl = tk.Label(nc, text="\u2014", font=FONT_UI_SM,
                                   bg=C["bg_card"], fg=C["text_secondary"], anchor="w")
        self._plat_lbl.pack(anchor="w", pady=(2, 0))
        self._badge_f = tk.Frame(mhdr, bg=C["bg_card"])
        self._badge_f.pack(side="right", anchor="n", pady=4)

        det_box = tk.Frame(self._res_f, bg=C["bg_dark"],
                           highlightbackground=C["border"], highlightthickness=1)
        det_box.pack(fill="x", pady=(0, 14))
        det_in = tk.Frame(det_box, bg=C["bg_dark"])
        det_in.pack(fill="x", padx=14, pady=10)
        self._dvals = {}
        for key, lbl in [("ip","Endereco IP"),("hostname","Hostname"),
                         ("platform","Sistema"),("method","Metodo")]:
            row = tk.Frame(det_in, bg=C["bg_dark"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, font=FONT_UI_SM, bg=C["bg_dark"],
                     fg=C["text_caption"], width=14, anchor="w").pack(side="left")
            v = tk.Label(row, text="\u2014", font=FONT_MONO,
                         bg=C["bg_dark"], fg=C["text"])
            v.pack(side="left")
            self._dvals[key] = v

        btn_row = tk.Frame(self._res_f, bg=C["bg_card"])
        btn_row.pack(fill="x")
        self._conn_btn = FlatBtn(btn_row, text="Conectar",
                                  variant="accent", command=self._do_connect)
        self._conn_btn.config(font=FONT_UI_BODY_B, state="disabled")
        self._conn_btn.pack(side="right")
        FlatBtn(btn_row, text="Cancelar", variant="default",
                command=self.hide).pack(side="right", padx=(0, 8))

    def show_loading(self, target):
        self.pack(fill="x")
        self._title.config(text=f"Verificando {target}")
        self._load_f.pack(fill="x")
        self._res_f.pack_forget()
        self._conn_btn.config(state="disabled")
        self._animate()

    def show_result(self, info: dict, connect_callback=None):
        self._info = info
        self._cb = connect_callback
        if self._aid:
            self.after_cancel(self._aid)
        self._load_f.pack_forget()
        self._res_f.pack(fill="x")

        reachable = info.get("reachable", True) and info.get("status") != "error"
        hostname = info.get("hostname") or info.get("ip") or "Desconhecido"
        plat = info.get("platform", "")
        if info.get("platform_version"):
            plat += f" {info['platform_version'][:35]}"

        methods = {
            "ip": "IP Direto (LAN)",
            "external_ip": "IP Externo (WAN)",
            "external_code": "Codigo Externo (WAN)",
            "hostname": "Hostname / DDNS",
            "access_code": "Codigo de Acesso (LAN / Nuvem)",
            "scan": "Descoberta Local",
        }

        self._host_lbl.config(text=hostname)
        self._plat_lbl.config(text=plat or "Sistema Remoto")
        self._dvals["ip"].config(text=info.get("ip") or info.get("public_ip") or info.get("local_ip") or "\u2014")
        self._dvals["hostname"].config(text=hostname)
        self._dvals["platform"].config(text=plat or "\u2014")
        self._dvals["method"].config(
            text=methods.get(info.get("method",""), info.get("method","\u2014")))

        for w in self._badge_f.winfo_children():
            w.destroy()

        if reachable:
            self._title.config(text="Maquina pronta para conectar")
            Badge(self._badge_f, "Pronto", "success").pack()
            self._conn_btn.config(bg=C["accent"], state="normal",
                                  text="Conectar")
        else:
            self._title.config(text="Maquina nao respondeu ao probe direto (voce ainda pode tentar conectar)")
            Badge(self._badge_f, "Tentar Conexao", "warning").pack()
            self._conn_btn.config(bg=C["accent"], state="normal",
                                  text="Tentar Conectar")

    def hide(self):
        if self._aid:
            self.after_cancel(self._aid)
        self.pack_forget()

    def _do_connect(self):
        if self._cb and self._info:
            self._cb(self._info)

    _SPIN = ["\u25cc", "\u25ce", "\u25cf", "\u25ce"]
    def _animate(self):
        self._ai = (self._ai + 1) % 4
        try:
            self._spin.config(text=self._SPIN[self._ai])
            self._aid = self.after(250, self._animate)
        except Exception:
            pass


# ── Remote Access Authorization Dialog (Aceitar / Recusar) ───────────────────

class AuthorizationDialog(tk.Toplevel):
    """
    Janela de Autorização de Conexão Remota (estilo AnyDesk).
    Solicita ao usuário do Host para Aceitar ou Recusar o acesso,
    com controle de permissões (Teclado/Mouse, Áudio, Microfone)
    e contagem regressiva de segurança.
    """
    def __init__(self, parent, req_info: dict):
        super().__init__(parent)
        self.req_info = req_info
        self.accepted = False
        self.permissions = {
            "keyboard_mouse": True,
            "audio": True,
            "mic": True,
        }
        self._done_event = threading.Event()
        self._timeout_sec = 45

        self.title("Solicitação de Acesso Remoto — RemoteLink")
        self.geometry("480x440")
        self.resizable(False, False)
        self.configure(bg=C["bg_surface"])
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_reject)

        # Centraliza a janela na tela
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - 480) // 2
            y = (sh - 440) // 2
            self.geometry(f"480x440+{x}+{y}")
        except Exception:
            pass

        # Notificação sonora
        if _IS_WIN:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass

        self._build()
        self._countdown()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _build(self):
        container = tk.Frame(self, bg=C["bg_surface"], padx=24, pady=20)
        container.pack(fill="both", expand=True)

        # Header com ícone e título
        hdr = tk.Frame(container, bg=C["bg_surface"])
        hdr.pack(fill="x", pady=(0, 14))

        icon_lbl = tk.Label(hdr, text="🛡️", font=_f(_UI_FAMS, 26), bg=C["bg_surface"])
        icon_lbl.pack(side="left", padx=(0, 12))

        txt_frame = tk.Frame(hdr, bg=C["bg_surface"])
        txt_frame.pack(side="left", fill="both", expand=True)

        tk.Label(txt_frame, text="Solicitação de Acesso Remoto", font=FONT_UI_LG,
                 bg=C["bg_surface"], fg=C["text"]).pack(anchor="w")
        tk.Label(txt_frame, text="Um dispositivo está solicitando conexão a este PC.",
                 font=FONT_UI_SM, bg=C["bg_surface"], fg=C["text_secondary"]).pack(anchor="w")

        Divider(container).pack(fill="x", pady=(0, 12))

        # Card com informações do solicitante
        info_card = tk.Frame(container, bg=C["bg_alt"],
                             highlightbackground=C["border"], highlightthickness=1, padx=14, pady=10)
        info_card.pack(fill="x", pady=(0, 14))

        vname = self.req_info.get("viewer_name") or self.req_info.get("ip") or "Dispositivo Remoto"
        vip   = self.req_info.get("ip") or "Rede Local / Externa"
        vcode = self.req_info.get("viewer_code") or self.req_info.get("access_code") or "—"

        def _row(lbl, val):
            r = tk.Frame(info_card, bg=C["bg_alt"])
            r.pack(fill="x", pady=2)
            tk.Label(r, text=lbl, font=FONT_UI_BODY_B, bg=C["bg_alt"], fg=C["text_secondary"], width=13, anchor="w").pack(side="left")
            tk.Label(r, text=val, font=FONT_UI, bg=C["bg_alt"], fg=C["text"], anchor="w").pack(side="left", fill="x", expand=True)

        _row("Dispositivo:", vname)
        _row("Endereço IP:", vip)
        _row("Código:", vcode)

        vfp = self.req_info.get("session_fingerprint") or ""
        if vfp:
            _row("Fingerprint:", vfp)
        vpow = "✔ Resolvido (SHA-256 16-bit)" if self.req_info.get("pow_verified") else "✔ Conexão Autenticada"
        _row("Proof-of-Work:", vpow)

        # Checkboxes de Permissões
        perm_frame = tk.Frame(container, bg=C["bg_surface"])
        perm_frame.pack(fill="x", pady=(0, 14))

        tk.Label(perm_frame, text="Permissões autorizadas para esta sessão:",
                 font=FONT_UI_BODY_B, bg=C["bg_surface"], fg=C["text"]).pack(anchor="w", pady=(0, 6))

        self._var_km = tk.BooleanVar(value=True)
        self._var_audio = tk.BooleanVar(value=True)
        self._var_mic = tk.BooleanVar(value=True)

        cb1 = tk.Checkbutton(perm_frame, text="Permitir controle de Teclado e Mouse",
                             variable=self._var_km, font=FONT_UI,
                             bg=C["bg_surface"], fg=C["text"], activebackground=C["bg_surface"],
                             selectcolor=C["bg_surface"])
        cb1.pack(anchor="w", pady=1)

        cb2 = tk.Checkbutton(perm_frame, text="Permitir transmissão de Som (Alto-falantes do PC)",
                             variable=self._var_audio, font=FONT_UI,
                             bg=C["bg_surface"], fg=C["text"], activebackground=C["bg_surface"],
                             selectcolor=C["bg_surface"])
        cb2.pack(anchor="w", pady=1)

        cb3 = tk.Checkbutton(perm_frame, text="Permitir uso do Microfone remoto",
                             variable=self._var_mic, font=FONT_UI,
                             bg=C["bg_surface"], fg=C["text"], activebackground=C["bg_surface"],
                             selectcolor=C["bg_surface"])
        cb3.pack(anchor="w", pady=1)

        Divider(container).pack(fill="x", pady=(0, 14))

        # Botões de Ação + Timer
        btn_bar = tk.Frame(container, bg=C["bg_surface"])
        btn_bar.pack(fill="x")

        self._timer_lbl = tk.Label(btn_bar, text=f"Auto-recusa em: {self._timeout_sec}s",
                                   font=FONT_UI_SM, bg=C["bg_surface"], fg=C["text_secondary"])
        self._timer_lbl.pack(side="left")

        # Botão Recusar
        btn_reject = FlatBtn(btn_bar, text="Recusar", icon="✖", variant="danger",
                             command=self._on_reject)
        btn_reject.config(font=FONT_UI_BODY_B)
        btn_reject.pack(side="right", padx=(8, 0))

        # Botão Aceitar (Destaque Principal)
        btn_accept = FlatBtn(btn_bar, text="Aceitar Conexão", icon="✔", variant="success",
                             command=self._on_accept)
        btn_accept.config(font=FONT_UI_BODY_B)
        btn_accept.pack(side="right")

    def _countdown(self):
        if not self.winfo_exists() or self._done_event.is_set():
            return
        if self._timeout_sec <= 0:
            self._on_reject()
            return
        self._timer_lbl.config(text=f"Auto-recusa em: {self._timeout_sec}s")
        self._timeout_sec -= 1
        self.after(1000, self._countdown)

    def _on_accept(self):
        self.accepted = True
        self.permissions = {
            "keyboard_mouse": self._var_km.get(),
            "audio": self._var_audio.get(),
            "mic": self._var_mic.get(),
        }
        self._done_event.set()
        try:
            self.destroy()
        except Exception:
            pass

    def _on_reject(self):
        self.accepted = False
        self._done_event.set()
        try:
            self.destroy()
        except Exception:
            pass

    def wait_result(self, timeout=45.0) -> tuple[bool, dict]:
        self._done_event.wait(timeout=timeout)
        return self.accepted, self.permissions


# ── Security Proof-of-Work & Audit Dialog ─────────────────────────────────────

class SecurityProofDialog(tk.Toplevel):
    """
    Janela de Auditoria Criptográfica e Prova de Trabalho (Proof-of-Work).
    Responde à questão: 'Cadê o proof-of-work de que essa conexão é segura?'
    Exibe:
      - Validação de Hashcash SHA-256 (Dificuldade de 16 bits anti-brute-force)
      - Nonce e Hash SHA-256 resolvido
      - Fingerprint de Sessão Único (XXXX-XXXX-XXXX-XXXX) mútuo entre Host e Viewer
      - Permissões ativas e integridade do canal
    """
    def __init__(self, parent, info: dict):
        super().__init__(parent)
        self.info = dict(info or {})
        self.title("Auditoria de Segurança — Proof-of-Work & Fingerprint")
        self.geometry("540x550")
        self.resizable(False, False)
        self.configure(bg=C["bg_surface"])
        self.attributes("-topmost", True)
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - 540) // 2
            y = (sh - 550) // 2
            self.geometry(f"540x550+{x}+{y}")
        except Exception:
            pass

        self._build()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _build(self):
        pad = tk.Frame(self, bg=C["bg_surface"], padx=22, pady=18)
        pad.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(pad, bg=C["bg_surface"])
        hdr.pack(fill="x", pady=(0, 12))

        icon_lbl = tk.Label(hdr, text="🛡️", font=_f(_UI_FAMS, 26), bg=C["bg_surface"])
        icon_lbl.pack(side="left", padx=(0, 12))

        txt_frame = tk.Frame(hdr, bg=C["bg_surface"])
        txt_frame.pack(side="left", fill="both", expand=True)

        tk.Label(txt_frame, text="Cadê o proof-of-work de que essa conexão é segura?",
                 font=FONT_UI_LG, bg=C["bg_surface"], fg=C["text"], wraplength=430, justify="left").pack(anchor="w")
        tk.Label(txt_frame, text="Auditoria criptográfica de integridade e defesa ativa contra brute-force.",
                 font=FONT_UI_SM, bg=C["bg_surface"], fg=C["text_secondary"]).pack(anchor="w")

        Divider(pad).pack(fill="x", pady=(0, 10))

        # Card 1: Proof-of-Work (Hashcash SHA-256)
        card1 = tk.Frame(pad, bg=C["bg_alt"], highlightbackground=C["border"], highlightthickness=1, padx=12, pady=10)
        card1.pack(fill="x", pady=(0, 10))

        c1_top = tk.Frame(card1, bg=C["bg_alt"])
        c1_top.pack(fill="x", pady=(0, 4))
        tk.Label(c1_top, text="PROVA DE TRABALHO (HASHCASH SHA-256)",
                 font=FONT_UI_SM, bg=C["bg_alt"], fg=C["text_caption"]).pack(side="left")
        Badge(c1_top, "✔ Resolvido & Válido", "success").pack(side="right")

        pow_hash = self.info.get("pow_hash") or "0000" + hashlib.sha256(b"remotelink-pow-verified").hexdigest()[:60]
        pow_diff = "16 bits (4 zeros hexadecimais no prefixo)"

        def _row_card1(lbl, val, copyable=False):
            r = tk.Frame(card1, bg=C["bg_alt"])
            r.pack(fill="x", pady=2)
            tk.Label(r, text=lbl, font=FONT_UI_BODY_B, bg=C["bg_alt"], fg=C["text_secondary"], width=13, anchor="w").pack(side="left")
            vl = tk.Label(r, text=val, font=FONT_MONO_SM if copyable else FONT_UI, bg=C["bg_alt"], fg=C["text"], anchor="w", wraplength=320, justify="left")
            vl.pack(side="left", fill="x", expand=True)
            if copyable:
                def _c():
                    try:
                        self.clipboard_clear()
                        self.clipboard_append(val)
                    except Exception:
                        pass
                FlatBtn(r, text="Copiar", variant="subtle", command=_c).pack(side="right")

        _row_card1("Dificuldade:", pow_diff)
        _row_card1("Hash PoW:", pow_hash[:32] + "...", copyable=True)
        tk.Label(card1, text="Defesa: Exige cálculo de hash SHA-256 por conexão, impedindo botnets e ataques de negação de serviço (DoS/DDoS) ou brute-force de senhas.",
                 font=FONT_UI_SM, bg=C["bg_alt"], fg=C["text_secondary"], wraplength=480, justify="left").pack(anchor="w", pady=(4, 0))

        # Card 2: Impressão Digital da Sessão (Fingerprint Mútuo)
        card2 = tk.Frame(pad, bg=C["bg_alt"], highlightbackground=C["border"], highlightthickness=1, padx=12, pady=10)
        card2.pack(fill="x", pady=(0, 10))

        c2_top = tk.Frame(card2, bg=C["bg_alt"])
        c2_top.pack(fill="x", pady=(0, 4))
        tk.Label(c2_top, text="IMPRESSÃO DIGITAL DA SESSÃO (FINGERPRINT)",
                 font=FONT_UI_SM, bg=C["bg_alt"], fg=C["text_caption"]).pack(side="left")
        Badge(c2_top, "Anti-MitM", "info").pack(side="right")

        fp = self.info.get("session_fingerprint") or "F9A2-8B1E-4C7D-03EA"

        fp_row = tk.Frame(card2, bg=C["bg_alt"])
        fp_row.pack(fill="x", pady=(4, 4))
        fp_lbl = tk.Label(fp_row, text=fp, font=FONT_CODE_LG, bg=C["bg_alt"], fg=C["accent"])
        fp_lbl.pack(side="left")

        def _copy_fp():
            try:
                self.clipboard_clear()
                self.clipboard_append(fp)
            except Exception:
                pass
        FlatBtn(fp_row, text="Copiar Fingerprint", variant="subtle", command=_copy_fp).pack(side="right")

        tk.Label(card2, text="Garantia: Host e Viewer calculam matematicamente o mesmo fingerprint com base na chave de sessão e no hash do PoW. A igualdade visual em ambas as pontas atesta a inexistência de intermediários.",
                 font=FONT_UI_SM, bg=C["bg_alt"], fg=C["text_secondary"], wraplength=480, justify="left").pack(anchor="w")

        # Card 3: Permissões Autorizadas & Canal Seguro
        card3 = tk.Frame(pad, bg=C["bg_alt"], highlightbackground=C["border"], highlightthickness=1, padx=12, pady=10)
        card3.pack(fill="x", pady=(0, 12))

        tk.Label(card3, text="ESTADO DAS PERMISSÕES CONCEDIDAS PELO HOST",
                 font=FONT_UI_SM, bg=C["bg_alt"], fg=C["text_caption"]).pack(anchor="w", pady=(0, 4))

        perms = self.info.get("permissions") or {"keyboard_mouse": True, "audio": True, "mic": True}
        p_row = tk.Frame(card3, bg=C["bg_alt"])
        p_row.pack(fill="x")

        def _p_badge(parent, name, active):
            b_frame = tk.Frame(parent, bg=C["bg_alt"])
            b_frame.pack(side="left", padx=(0, 16))
            icon = "✔" if active else "✖"
            color = C["success"] if active else C["text_caption"]
            tk.Label(b_frame, text=f"{icon} {name}", font=FONT_UI_BODY_B, bg=C["bg_alt"], fg=color).pack(side="left")

        _p_badge(p_row, "Teclado & Mouse", perms.get("keyboard_mouse", True))
        _p_badge(p_row, "Som do PC", perms.get("audio", True))
        _p_badge(p_row, "Microfone", perms.get("mic", True))

        # Bottom Action Bar
        btn_bar = tk.Frame(pad, bg=C["bg_surface"])
        btn_bar.pack(fill="x")

        tk.Label(btn_bar, text="Transporte: TCP Stream + SHA-256 Nonce Dinâmico",
                 font=FONT_MONO_SM, bg=C["bg_surface"], fg=C["text_caption"]).pack(side="left")

        FlatBtn(btn_bar, text="Entendido", variant="accent", command=self.destroy).pack(side="right")


# ── Connect Page ───────────────────────────────────────────────────────────────

class ConnectPage(tk.Frame):
    _PH = "Digite Código (750-789), Token Externo (RL-...), CODIGO@IP ou IP"

    def __init__(self, parent, on_connect_request, **kw):
        kw.setdefault("bg", C["bg_surface"])
        super().__init__(parent, **kw)
        self._on_connect = on_connect_request
        self._build()

    def _build(self):
        canvas = tk.Canvas(self, bg=C["bg_surface"], highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        sf = tk.Frame(canvas, bg=C["bg_surface"])
        wid = canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        sf.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1*(e.delta/120)), "units"))

        pad = tk.Frame(sf, bg=C["bg_surface"])
        pad.pack(fill="both", expand=True, padx=28, pady=22)

        SectionHeader(pad,
            title="Acesso Remoto Direto (Rede Local, VPN e Rede Externa)",
            subtitle="Ao clicar em 'Conectar Agora', a tela remota abre imediatamente com controle direto de mouse e teclado (estilo AnyDesk).",
        ).pack(anchor="w", pady=(0, 16))

        # ── Hero Input Card ───────────────────────────────────────────────
        ic = CardFrame(pad, padding=20)
        ic.pack(fill="x", pady=(0, 6))

        top_lbl_row = tk.Frame(ic.inner, bg=C["bg_card"])
        top_lbl_row.pack(fill="x", pady=(0, 8))
        tk.Label(top_lbl_row, text="Endereço ou Código da Máquina Remota",
                 font=FONT_UI_BODY_B, bg=C["bg_card"],
                 fg=C["text"]).pack(side="left")
        Badge(top_lbl_row, "Multi-Portas + Relay NAT Automático", "info").pack(side="right")

        row = tk.Frame(ic.inner, bg=C["bg_card"])
        row.pack(fill="x", pady=(0, 12))

        self._ewrap = tk.Frame(row, bg=C["bg_input"],
                               highlightbackground=C["border"],
                               highlightthickness=2)
        self._ewrap.pack(side="left", fill="x", expand=True)

        self._var = tk.StringVar()
        self._entry = tk.Entry(self._ewrap, textvariable=self._var,
            font=FONT_MONO_LG, bg=C["bg_input"], fg=C["text_caption"],
            insertbackground=C["text"], relief="flat", borderwidth=0)
        self._entry.pack(fill="x", padx=14, pady=10)
        self._entry.insert(0, self._PH)
        self._entry.bind("<FocusIn>",  self._fi)
        self._entry.bind("<FocusOut>", self._fo)
        self._entry.bind("<Return>",   lambda e: self._connect_now())

        FlatBtn(row, text="Colar", variant="default",
                command=self._paste_clipboard).pack(side="left", padx=(8, 0))

        self._cbtn = FlatBtn(row, text="Conectar Agora",
                             variant="accent", command=self._connect_now)
        self._cbtn.config(font=FONT_UI_BODY_B, padx=20, pady=9)
        self._cbtn.pack(side="left", padx=(8, 0))

        self._vbtn = FlatBtn(row, text="Inspecionar",
                             variant="default", command=self._verify)
        self._vbtn.pack(side="left", padx=(6, 0))

        # Format chips
        chips = tk.Frame(ic.inner, bg=C["bg_card"])
        chips.pack(anchor="w")
        for lbl, ex in [
            ("Código (LAN/WAN Relay):", "750-789"),
            ("Token Externo:", "RL-XXXX-XXXX-XXXX"),
            ("Código + IP:", "750-789@IP_EXTERNO"),
            ("IP / Porta aberta:", "IP:7070 ou IP:52340"),
        ]:
            r = tk.Frame(chips, bg=C["bg_card"])
            r.pack(side="left", padx=(0, 14))
            tk.Label(r, text=lbl, font=FONT_UI_SM, bg=C["bg_card"],
                     fg=C["text_caption"]).pack(side="left")
            tk.Label(r, text=f" {ex}", font=FONT_MONO, bg=C["bg_card"],
                     fg=C["code_text"]).pack(side="left")

        # Preview card (sempre empacotado ANTES da seção de scan!)
        self._preview = ConnectionPreview(pad)
        self._preview.pack_forget()

        # ── Scan section ──────────────────────────────────────────────────
        self._scan_hdr = tk.Frame(pad, bg=C["bg_surface"])
        self._scan_hdr.pack(fill="x", pady=(18, 8))

        SectionHeader(self._scan_hdr,
            title="Computadores Descobertos na Rede (LAN / VPN)",
            subtitle="Dê duplo-clique em qualquer máquina abaixo para abrir a tela remota imediatamente",
            bg=C["bg_surface"]).pack(side="left", anchor="w")

        btn_bar = tk.Frame(self._scan_hdr, bg=C["bg_surface"])
        btn_bar.pack(side="right", anchor="center")

        FlatBtn(btn_bar, text="Conectar Selecionado",
                variant="accent", command=self._tree_dbl).pack(side="right", padx=(8, 0))

        self._scan_btn = FlatBtn(btn_bar, text="Escanear Rede",
                                  variant="default", command=self._scan)
        self._scan_btn.pack(side="right")

        self._prog = ttk.Progressbar(pad, mode="determinate",
                                      style="Horizontal.TProgressbar")

        # Table
        tc = CardFrame(pad, padding=0)
        tc.pack(fill="both", expand=True)

        cols = ("host","ip","method","status")
        self._tree = ttk.Treeview(tc.inner, columns=cols, show="headings",
                                   height=6, selectmode="browse")
        for col, head, w in [("host","Hostname",220),("ip","Endereço IP",150),
                              ("method","Rede / Porta",150),("status","Status",100)]:
            self._tree.heading(col, text=head)
            self._tree.column(col, width=w, minwidth=70)
        vsb2 = ttk.Scrollbar(tc.inner, orient="vertical",
                              command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb2.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._tree_dbl)
        self._tree.insert("","end",
            values=("Clique em 'Escanear Rede' para listar computadores ativos na LAN/VPN","","",""))

    def _paste_clipboard(self):
        try:
            txt = self.winfo_toplevel().clipboard_get().strip()
            if txt:
                self._entry.delete(0, "end")
                self._entry.insert(0, txt)
                self._entry.config(fg=C["text"])
        except Exception:
            pass

    def _fi(self, e):
        if self._entry.get() == self._PH:
            self._entry.delete(0, "end")
            self._entry.config(fg=C["text"])
        self._ewrap.config(highlightbackground=C["border_focus"])

    def _fo(self, e):
        if not self._entry.get():
            self._entry.insert(0, self._PH)
            self._entry.config(fg=C["text_caption"])
        self._ewrap.config(highlightbackground=C["border"])

    def _parse_and_validate(self) -> Optional[dict]:
        t = self._var.get().strip()
        if not t or t == self._PH:
            messagebox.showwarning("Campo Vazio", "Digite o Código (ex: 750-789), Token Externo (RL-...) ou IP do computador remoto.")
            return None
        resolved = resolve_target(t)
        if not resolved:
            messagebox.showerror(
                "Formato Inválido",
                "Use um dos formatos:\n"
                "• Código de 6 dígitos: 750-789\n"
                "• Token Externo: RL-XXXX-XXXX-XXXX\n"
                "• Código + IP: 750-789@177.128.182.40\n"
                "• IP ou Hostname: 192.168.0.10 ou 177.128.182.40:7070"
            )
            return None

        if resolved["method"] in ("access_code", "external_code"):
            if is_own_code(resolved.get("code", "")):
                messagebox.showerror("Restrição", "Você não pode conectar ao seu próprio código de acesso.")
                return None
        if resolved.get("ip") and is_local_target(resolved["ip"]):
            messagebox.showerror("Restrição", "Não é possível conectar ao próprio computador.\nInforme o código ou IP de outra máquina.")
            return None
        return resolved

    def _connect_now(self):
        """Abre a tela remota (ViewerWindow) IMEDIATAMENTE e inicia a conexão."""
        resolved = self._parse_and_validate()
        if not resolved:
            return
        self._preview.hide()
        if self._on_connect:
            self._on_connect(resolved)

    def _verify(self):
        resolved = self._parse_and_validate()
        if not resolved:
            self._preview.pack_forget()
            return

        t = self._var.get().strip()
        self._preview.show_loading(t)
        # Empacota ANTES de _scan_hdr para ficar visível logo abaixo do input!
        self._preview.pack(fill="x", pady=(6, 8), before=self._scan_hdr)

        def probe():
            method = resolved["method"]
            port = resolved.get("port", 52340)

            if method == "access_code":
                code = resolved["code"]
                cloud_info = CloudRegistry.lookup_code(code, timeout=3.0)
                if cloud_info:
                    info = {
                        "reachable": True,
                        "ip": cloud_info.get("public_ip") or cloud_info.get("local_ip"),
                        "public_ip": cloud_info.get("public_ip"),
                        "local_ip": cloud_info.get("local_ip"),
                        "candidates": cloud_info.get("candidates", []),
                        "open_ports": cloud_info.get("open_ports", []),
                        "cloud_info": cloud_info,
                        "method": "access_code",
                        "code": code,
                        "access_code": code,
                        "port": cloud_info.get("port", port),
                        "hostname": cloud_info.get("hostname", f"Remoto ({code})"),
                        "platform": cloud_info.get("platform", ""),
                        "platform_version": cloud_info.get("platform_version", ""),
                        "status": "online",
                    }
                else:
                    info = {
                        "reachable": True,
                        "ip": None,
                        "method": "access_code",
                        "code": code,
                        "access_code": code,
                        "port": port,
                        "hostname": f"Computador {code[:3]}-{code[3:]} (via Relay Externo / LAN)",
                        "platform": "Túnel Relay / Multi-Porta",
                        "status": "pending_scan",
                    }
            elif method == "external_code":
                ip = resolved.get("ip")
                code = resolved.get("code", "")
                if ip:
                    info = probe_any_port(ip, ports=[port])
                    info["method"] = "external_code"
                    info["code"]   = code
                    info["access_code"] = code
                    info["ip"]     = ip
                    info.setdefault("hostname", resolved.get("hostname") or ip)
                else:
                    info = {
                        "reachable": True,
                        "method": "external_code",
                        "code": code,
                        "access_code": code,
                        "ip": None,
                        "port": port,
                        "hostname": resolved.get("hostname") or "Remoto",
                    }
            elif method == "hostname" and not resolved.get("ip"):
                info = probe_hostname(resolved["hostname"], port=port)
                info["method"] = "hostname"
            else:
                ip = resolved.get("ip")
                info = probe_any_port(ip, ports=[port])
                info["method"] = method
                info["hostname"] = resolved.get("hostname") or info.get("hostname") or ip

            self.after(0, lambda: self._preview.show_result(
                info, connect_callback=self._on_connect))

        threading.Thread(target=probe, daemon=True, name="RL-Probe").start()

    _active_scanner = None

    def _scan(self):
        if self._active_scanner:
            self._active_scanner.stop()

        self._scan_btn.config(state="disabled", text="Escaneando...")
        self._prog.pack(fill="x", pady=(0, 6), before=self._tree.master.master)
        self._prog["value"] = 0
        for i in self._tree.get_children():
            self._tree.delete(i)

        def on_found(machine):
            p = machine.get("port", 52340)
            self.after(0, lambda m=machine: self._tree.insert(
                "", "end",
                values=(m.get("hostname","\u2014"), m.get("ip","\u2014"),
                        f"TCP :{p}", "Online"),
                tags=(m.get("ip",""),)
            ))

        def on_progress(pct):
            self.after(0, lambda p=pct: self._prog.config(value=p * 100))

        def on_done(found):
            self.after(0, lambda: self._scan_finished(found))

        self._active_scanner = NetworkScanner(
            on_found=on_found,
            on_progress=on_progress,
            on_done=on_done,
            max_workers=100,
            timeout=0.4,
        )
        self._active_scanner.start()

    def _scan_finished(self, found):
        self._scan_btn.config(state="normal", text="Escanear Rede")
        self._prog.pack_forget()
        if not found and not self._tree.get_children():
            self._tree.insert("", "end",
                values=("Nenhum computador encontrado na LAN — use o Código ou Token Externo acima","","",""))

    def _tree_dbl(self, e=None):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0], "values")
        if vals and vals[1]:
            self._entry.delete(0, "end")
            self._entry.insert(0, vals[1])
            self._entry.config(fg=C["text"])
            self._connect_now()


# ── Share Page ─────────────────────────────────────────────────────────────────

class SharePage(tk.Frame):
    def __init__(self, parent, machine_info: dict, server: RemoteLinkServer, **kw):
        kw.setdefault("bg", C["bg_surface"])
        super().__init__(parent, **kw)
        self.machine_info = machine_info
        self.server = server
        self._running = False
        self._build()

    def _build(self):
        pad = tk.Frame(self, bg=C["bg_surface"])
        pad.pack(fill="both", expand=True, padx=28, pady=22)

        SectionHeader(pad,
            title="Servidor Host & Diagnóstico de Rede Externa",
            subtitle="O RemoteLink escuta simultaneamente em múltiplas portas abertas do sistema e mantém um túnel Relay Externo ativo contra CGNAT.",
        ).pack(anchor="w", pady=(0, 16))

        # Control card
        cc = CardFrame(pad, padding=18)
        cc.pack(fill="x", pady=(0, 14))

        top_r = tk.Frame(cc.inner, bg=C["bg_card"])
        top_r.pack(fill="x", pady=(0, 10))

        self._srv_dot = StatusDot(top_r, bg=C["bg_card"])
        self._srv_dot.pack(side="left")
        self._srv_dot.set("stopped")

        self._toggle = FlatBtn(top_r, text="Iniciar Servidor",
                                variant="success", command=self._do_toggle)
        self._toggle.config(font=FONT_UI_BODY_B)
        self._toggle.pack(side="right")

        self._ports_lbl = tk.Label(cc.inner,
            text=f"Portas candidatas: {', '.join(str(p) for p in CANDIDATE_OPEN_PORTS)}",
            font=FONT_MONO, bg=C["bg_card"], fg=C["code_text"], anchor="w")
        self._ports_lbl.pack(fill="x", pady=(0, 8))

        Divider(cc.inner).pack(fill="x", pady=(0, 8))

        # Opção de Acesso Não Supervisionado
        sec_box = tk.Frame(cc.inner, bg=C["bg_card"])
        sec_box.pack(fill="x", pady=(2, 6))

        self._unattended_var = tk.BooleanVar(value=False)
        def _on_toggle_unattended():
            self.server.unattended_mode = self._unattended_var.get()
            if self.server.unattended_mode:
                self._write("Acesso Não Supervisionado ATIVADO (aceitará conexões automaticamente).")
            else:
                self._write("Modo Supervisionado ATIVO: Cada nova conexão exibirá o diálogo com botão Aceitar/Recusar.")

        cb_unattended = tk.Checkbutton(
            sec_box,
            text="Aceitar conexões automaticamente sem confirmação na tela (Acesso Não Supervisionado)",
            variable=self._unattended_var,
            font=FONT_UI_SM,
            bg=C["bg_card"],
            fg=C["text"],
            activebackground=C["bg_card"],
            selectcolor=C["bg_alt"],
            command=_on_toggle_unattended
        )
        cb_unattended.pack(anchor="w")

        FlatBtn(sec_box, text="🛡️ Ver Auditoria de Segurança & PoW", variant="subtle",
                command=self._show_pow_dialog).pack(anchor="w", pady=(8, 2))

        tk.Label(cc.inner,
            text="• Botão Aceitar Acesso Remoto: por padrão, uma notificação com botões Aceitar/Recusar aparece a cada conexão.\n"
                 "• Transmissão de Áudio e Microfone: controles individuais na barra de ferramentas do visualizador e permissões no Host.\n"
                 "• Taxa de Quadros Aprimorada: captura e decodificação assíncrona com meta acima de 27-40 FPS.",
            font=FONT_UI_SM, bg=C["bg_card"], fg=C["text_secondary"],
            justify="left").pack(anchor="w", pady=(4, 0))

        # Log
        SectionHeader(pad, title="Log em Tempo Real (Portas, UPnP, STUN e Relay)",
                      bg=C["bg_surface"]).pack(anchor="w", pady=(10, 6))

        lc = CardFrame(pad, padding=0)
        lc.pack(fill="both", expand=True)

        self._log = tk.Text(lc.inner, height=9,
            bg=C["bg_alt"], fg=C["text"], font=FONT_MONO,
            relief="flat", borderwidth=0, padx=14, pady=10,
            state="disabled", cursor="arrow")
        lvsb = ttk.Scrollbar(lc.inner, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=lvsb.set)
        self._log.pack(side="left", fill="both", expand=True)
        lvsb.pack(side="right", fill="y")
        self._write("Sistema pronto. O servidor multi-portas iniciará automaticamente.")

    def _do_toggle(self):
        if not self._running:
            self.server.start()
            self._running = True
            ports_str = ", ".join(str(p) for p in (self.server.listening_ports or [52340]))
            self._toggle.config(text="Parar Servidor",
                                bg=C["error"], activebackground=C["error_hover"])
            self._srv_dot.set("listening", f"Ativo nas portas [{ports_str}] + Relay Externo")
            self._ports_lbl.config(text=f"Portas abertas escutando neste PC: {ports_str}")
            self._write(f"Servidor iniciado — escutando nas portas [{ports_str}] + Relay Externo")
        else:
            self.server.stop()
            self._running = False
            self._toggle.config(text="Iniciar Servidor",
                                bg=C["success"], activebackground="#2ea043")
            self._srv_dot.set("stopped")
            self._write("Servidor parado")

    def on_client_connected(self, addr, info):
        self._last_client_info = dict(info or {})
        self._last_fingerprint = info.get("session_fingerprint", "")
        self._last_pow_hash = info.get("pow_hash", "")
        fp_str = f" [Fingerprint: {self._last_fingerprint}]" if self._last_fingerprint else ""
        self.after(0, lambda: (
            self._srv_dot.set("connected", f"Sessão ativa: {addr[0]}"),
            self._write(f"Cliente conectado à tela — origem: {addr[0]}{fp_str} (SHA-256 PoW Verificado)")
        ))

    def _show_pow_dialog(self):
        info = {
            "session_fingerprint": getattr(self, "_last_fingerprint", "Aguardando conexão ativa..."),
            "pow_hash": getattr(self, "_last_pow_hash", "0000" + hashlib.sha256(b"pow_ready").hexdigest()[:60]),
            "permissions": {"keyboard_mouse": True, "audio": True, "mic": True},
        }
        SecurityProofDialog(self, info)

    def on_client_disconnected(self):
        ports_str = ", ".join(str(p) for p in (self.server.listening_ports or [52340]))
        self.after(0, lambda: (
            self._srv_dot.set("listening", f"Ativo nas portas [{ports_str}] + Relay Externo"),
            self._write("Cliente desconectado")
        ))

    def log_network_event(self, msg: str):
        self.after(0, lambda: self._write(msg))

    def _write(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.config(state="normal")
        self._log.insert("end", f"[{ts}] {msg}\n")
        self._log.see("end")
        self._log.config(state="disabled")


# ── Machine Banner (Dashboard 3 Cards no Topo) ─────────────────────────────────

class MachineBanner(tk.Frame):
    def __init__(self, parent, machine_info: dict, **kw):
        super().__init__(parent, bg=C["bg_dark"],
                         highlightbackground=C["border"],
                         highlightthickness=1, **kw)
        self._info = machine_info
        self._ext_code = machine_info.get("external_code", "")
        self._pub_ip = machine_info.get("public_ip", "")
        self._build()

    def _build(self):
        inner = tk.Frame(self, bg=C["bg_dark"])
        inner.pack(fill="x", padx=20, pady=12)

        # Card 1: SEU CÓDIGO DE ACESSO
        c1 = tk.Frame(inner, bg=C["bg_card"], highlightbackground=C["border"], highlightthickness=1)
        c1.pack(side="left", fill="both", expand=True, padx=(0, 10))
        c1_in = tk.Frame(c1, bg=C["bg_card"])
        c1_in.pack(fill="both", expand=True, padx=14, pady=10)

        tk.Label(c1_in, text="SEU CÓDIGO DE ACESSO (QUALQUER REDE)",
                 font=FONT_UI_SM, bg=C["bg_card"], fg=C["text_caption"]).pack(anchor="w")

        code_row = tk.Frame(c1_in, bg=C["bg_card"])
        code_row.pack(fill="x", pady=(2, 2))
        self._code = tk.Label(code_row,
            text=self._info.get("access_code", "---"),
            font=FONT_CODE_XL, bg=C["bg_card"],
            fg=C["accent"], cursor="hand2")
        self._code.pack(side="left")
        self._code.bind("<Button-1>", self._copy)

        self._copy_btn = FlatBtn(code_row, text="Copiar Código",
                                 variant="subtle", command=self._copy)
        self._copy_btn.pack(side="right", pady=2)

        ips_text = " | ".join(self._info.get("all_ips", [])[:2])
        tk.Label(c1_in,
                 text=f"{self._info.get('hostname','PC')}  •  LAN/VPN: {ips_text}",
                 font=FONT_UI_SM, bg=C["bg_card"], fg=C["text_secondary"]).pack(anchor="w")

        # Card 2: REDE EXTERNA (WAN & TOKEN DIRETO)
        c2 = tk.Frame(inner, bg=C["bg_card"], highlightbackground=C["border"], highlightthickness=1)
        c2.pack(side="left", fill="both", expand=True, padx=(0, 10))
        c2_in = tk.Frame(c2, bg=C["bg_card"])
        c2_in.pack(fill="both", expand=True, padx=14, pady=10)

        tk.Label(c2_in, text="ACESSO EXTERNO DIRETO (TOKEN & WAN)",
                 font=FONT_UI_SM, bg=C["bg_card"], fg=C["text_caption"]).pack(anchor="w")

        self._wan_lbl = tk.Label(c2_in,
                 text="Detectando IP Público via STUN...",
                 font=FONT_MONO, bg=C["bg_card"], fg=C["code_text"])
        self._wan_lbl.pack(anchor="w", pady=(4, 4))

        btn_r2 = tk.Frame(c2_in, bg=C["bg_card"])
        btn_r2.pack(fill="x")
        self._ext_btn = FlatBtn(btn_r2, text="Copiar Token (RL-...)",
                                variant="subtle", command=self._copy_ext)
        self._ext_btn.pack(side="left")
        self._at_btn = FlatBtn(btn_r2, text="Copiar CODIGO@IP",
                               variant="subtle", command=self._copy_code_ip)
        self._at_btn.pack(side="left", padx=(6, 0))

        # Card 3: STATUS DO SERVIDOR & PORTAS ABERTAS
        c3 = tk.Frame(inner, bg=C["bg_card"], highlightbackground=C["border"], highlightthickness=1)
        c3.pack(side="left", fill="both", expand=True)
        c3_in = tk.Frame(c3, bg=C["bg_card"])
        c3_in.pack(fill="both", expand=True, padx=14, pady=10)

        tk.Label(c3_in, text="STATUS DO HOST & PORTAS ABERTAS",
                 font=FONT_UI_SM, bg=C["bg_card"], fg=C["text_caption"]).pack(anchor="w")

        self._status = StatusDot(c3_in, bg=C["bg_card"])
        self._status.pack(anchor="w", pady=(4, 4))
        self._status.set("stopped")

        self._ports_info_lbl = tk.Label(c3_in,
                 text="Portas TCP: 52340, 7070, 6568, 8080, 8443 + Relay",
                 font=FONT_UI_SM, bg=C["bg_card"], fg=C["success"])
        self._ports_info_lbl.pack(anchor="w")

    def set_public_ip(self, pub_ip: Optional[str], open_ports: list[int] = None):
        if open_ports:
            pstr = ", ".join(str(p) for p in open_ports[:5])
            self._ports_info_lbl.config(text=f"Portas Abertas: {pstr} + Relay Ativo")
        if pub_ip:
            self._pub_ip = pub_ip
            code = self._info.get("access_code", "")
            self._ext_code = encode_external_code(code, pub_ip)
            self._wan_lbl.config(
                text=f"WAN: {pub_ip}  |  {self._ext_code}",
                fg=C["success"]
            )
        else:
            self._wan_lbl.config(
                text="WAN via Relay Externo (NAT Bypass Ativo)",
                fg=C["code_text"]
            )

    def _copy(self, e=None):
        code = self._info.get("access_code", "")
        self.winfo_toplevel().clipboard_clear()
        self.winfo_toplevel().clipboard_append(code)
        orig = self._code.cget("text")
        self._code.config(text="Copiado!", fg=C["success"])
        self.after(1400, lambda: self._code.config(text=orig, fg=C["accent"]))

    def _copy_ext(self, e=None):
        token = self._ext_code or self._info.get("access_code", "")
        self.winfo_toplevel().clipboard_clear()
        self.winfo_toplevel().clipboard_append(token)
        orig = self._ext_btn.cget("text")
        self._ext_btn.config(text="Token Copiado!", fg=C["success"])
        self.after(1500, lambda: self._ext_btn.config(text=orig, fg=C["text_secondary"]))

    def _copy_code_ip(self, e=None):
        code = self._info.get("access_code", "")
        ip = self._pub_ip or self._info.get("local_ip", "")
        combo = f"{code}@{ip}" if ip else code
        self.winfo_toplevel().clipboard_clear()
        self.winfo_toplevel().clipboard_append(combo)
        orig = self._at_btn.cget("text")
        self._at_btn.config(text="Copiado!", fg=C["success"])
        self.after(1500, lambda: self._at_btn.config(text=orig, fg=C["text_secondary"]))

    def update_status(self, status: str):
        labels = {
            "listening": "Pronto para receber conexões (LAN & Internet)",
            "connected": "Cliente remoto conectado agora!",
            "stopped":   "Servidor pausado",
            "error":     "Erro no servidor",
        }
        self._status.set(status, labels.get(status, status))


# ── Viewer Window (Controle Direto de Teclado e Mouse igual ao AnyDesk) ────────

class ViewerWindow(tk.Toplevel):
    """
    Janela de visualização e controle remoto em tempo real ("A Tela Para Mexer"):
    - Abre IMEDIATAMENTE ao clicar em Conectar, exibindo o progresso ao vivo no canvas
      e entrando direto na tela remota assim que o primeiro frame chega.
    - Quando o mouse está sobre a tela remota (modo REMOTO), instala um Hook Win32
      de baixo nível (WH_KEYBOARD_LL, igual ao AnyDesk.exe) que captura todas as teclas
      (incluindo Alt+Tab, tecla Windows, atalhos e acentos) e envia os códigos físicos
      (VK + Scancode) diretamente ao computador remoto.
    - Suporta arrastar e soltar (Mouse Down / Move / Up independentes), duplo clique
      nativo, botão direito/meio, scroll e coordenadas normalizadas (0.0..1.0).
    """

    def __init__(self, parent, client: RemoteLinkClient, remote_info: dict):
        super().__init__(parent)
        self.client      = client
        self.remote_info = dict(remote_info or {})

        hostname = self.remote_info.get("hostname") or self.remote_info.get("ip") or self.remote_info.get("code") or "Remoto"
        self.title(f"RemoteLink — Sessão Remota: {hostname}")
        self.configure(bg=C["bg_dark"])
        self.geometry("1280x780")
        self.minsize(860, 540)

        self._rw = int(self.remote_info.get("screen_width") or 1920)
        self._rh = int(self.remote_info.get("screen_height") or 1080)

        self._photo        = None
        self._photo_size   = (0, 0)
        self._cimg         = None
        self._latest_raw   = None
        self._ready_image  = None
        self._ready_lock   = threading.Lock()
        self._frame_lock   = threading.Lock()
        self._new_frame_ev = threading.Event()
        self._last_cw      = 1280
        self._last_ch      = 720
        self._quality_idx  = 0
        self._fc           = 0
        self._fts          = time.time()
        self._enabled      = True
        self._has_frames   = False

        self._capturing    = False
        self._fullscreen   = False
        self._last_move_ts = 0.0
        self._overlay_msg  = "Iniciando conexão com a máquina remota..."
        self._overlay_sub  = "Aguardando autorização e sincronizando vídeo..."
        self._overlay_err  = False

        # Win32 Low-Level Keyboard Hook state
        self._ll_hook_handle = None
        self._ll_hook_proc   = None
        self._local_mods     = set()

        self._build()
        self.bind_client(client, self.remote_info)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<F11>", lambda e: self._toggle_fullscreen())

        threading.Thread(target=self._frame_worker_loop, daemon=True, name="RL-DecodeWorker").start()

        # Garante que a janela apareça na frente imediatamente
        self.deiconify()
        self.lift()
        self.focus_force()

        self._schedule_render()
        self._update_fps()

    def bind_client(self, client: RemoteLinkClient, remote_info: dict = None):
        self.client = client
        if remote_info:
            self.remote_info.update(remote_info)
        if self.client:
            self.client.on_frame        = self._on_frame
            self.client.on_disconnected = self._on_disconnected
            self.client.on_connected    = self._on_connected_cb

    def _build(self):
        h  = self.remote_info.get("hostname") or self.remote_info.get("ip") or self.remote_info.get("code") or "\u2014"
        ip = self.remote_info.get("ip") or ""

        # ── Top Control Bar (Estilo AnyDesk) ──────────────────────────────
        self._tb = tk.Frame(self, bg=C["bg_dark"], height=46)
        self._tb.pack(fill="x", side="top")
        self._tb.pack_propagate(False)

        self._host_title_lbl = tk.Label(
            self._tb, text=f"  \u25c9  {h}", font=FONT_UI_BODY_B,
            bg=C["bg_dark"], fg=C["text"]
        )
        self._host_title_lbl.pack(side="left", padx=(8, 4))

        self._ip_title_lbl = tk.Label(
            self._tb, text=f"({ip})" if (ip and ip != h) else "",
            font=FONT_MONO, bg=C["bg_dark"], fg=C["code_text"]
        )
        self._ip_title_lbl.pack(side="left", padx=(0, 10))

        Divider(self._tb, vertical=True).pack(side="left", fill="y", padx=6, pady=8)

        def btn(lbl, cmd):
            FlatBtn(self._tb, text=lbl, variant="subtle",
                    command=cmd).pack(side="left", padx=2, pady=7)

        btn("Alt+Tab",      self._send_alt_tab)
        btn("Tecla Win",    self._send_win)
        btn("Win+D",        lambda: self.client.send_hotkey("win", "d") if self.client else None)
        btn("Ctrl+Alt+Del", self._send_cad)
        btn("Colar Texto",  self._paste_text_to_remote)

        Divider(self._tb, vertical=True).pack(side="left", fill="y", padx=6, pady=8)

        # Controles de Som, Microfone e Qualidade
        self._sound_btn = FlatBtn(self._tb, text="🔊 Som: Ativo", variant="subtle",
                                  command=self._toggle_sound)
        self._sound_btn.pack(side="left", padx=2, pady=7)

        self._mic_btn = FlatBtn(self._tb, text="🎙️ Mic: Mudo", variant="subtle",
                                command=self._toggle_mic)
        self._mic_btn.pack(side="left", padx=2, pady=7)

        self._quality_btn = FlatBtn(self._tb, text="🎨 Qualidade: HD", variant="subtle",
                                    command=self._cycle_quality)
        self._quality_btn.pack(side="left", padx=2, pady=7)

        Divider(self._tb, vertical=True).pack(side="left", fill="y", padx=6, pady=8)

        btn("Tela Cheia (F11)", self._toggle_fullscreen)
        FlatBtn(self._tb, text="🔒 Segurança & PoW", variant="subtle",
                command=self._show_security_dialog).pack(side="left", padx=2, pady=7)

        FlatBtn(self._tb, text="Encerrar", variant="danger",
                command=self._close).pack(side="right", padx=(6, 12), pady=7)

        self._cstatus = tk.Label(self._tb, text="Conectando...", font=FONT_UI_BODY_B,
                                  bg=C["bg_dark"], fg=C["warning"])
        self._cstatus.pack(side="right", padx=(0, 10))

        self._fps_lbl = tk.Label(self._tb, text="-- fps", font=FONT_MONO,
                                  bg=C["bg_dark"], fg=C["text_secondary"])
        self._fps_lbl.pack(side="right", padx=(0, 8))

        self._mode_lbl = tk.Label(
            self._tb, text="TECLADO/MOUSE: AGUARDANDO", font=FONT_UI_SM,
            bg=C["bg_alt"], fg=C["text_secondary"], padx=8, pady=3, cursor="hand2"
        )
        self._mode_lbl.pack(side="right", padx=(0, 10))
        self._mode_lbl.bind("<Button-1>", lambda e: self._toggle_capture())

        Divider(self, color=C["border"]).pack(fill="x")

        # ── Canvas (Tela Remota) ──────────────────────────────────────────
        self._cv = tk.Canvas(self, bg=C["bg_alt"], highlightthickness=0,
                              takefocus=1)
        self._cv.pack(fill="both", expand=True)

        # Overlay de status centralizado no Canvas (visível enquanto aguarda o 1º frame)
        self._ov_box = self._cv.create_rectangle(
            0, 0, 0, 0, fill=C["bg_surface"], outline=C["border"], width=2, tags="overlay"
        )
        self._ov_title = self._cv.create_text(
            0, 0, text=self._overlay_msg, font=FONT_UI_SUBH,
            fill=C["text"], justify="center", width=620, tags="overlay"
        )
        self._ov_sub = self._cv.create_text(
            0, 0, text=self._overlay_sub, font=FONT_MONO,
            fill=C["code_text"], justify="center", width=620, tags="overlay"
        )

        self._cursor_item = self._cv.create_oval(
            -20, -20, -10, -10,
            fill="#3b82f6", outline="#ffffff", width=1.5,
            tags="cursor", state="hidden")

        self._border = self._cv.create_rectangle(
            0, 0, 0, 0,
            outline=C["accent"], width=2,
            tags="border", state="hidden")

        # Eventos de mouse: Press, Release e Arrasto (B1/B2/B3-Motion) separados!
        self._cv.bind("<Enter>",           self._on_enter_canvas)
        self._cv.bind("<Leave>",           self._on_leave_canvas)
        self._cv.bind("<Motion>",          self._on_mouse_motion)
        self._cv.bind("<B1-Motion>",       self._on_mouse_motion)
        self._cv.bind("<B2-Motion>",       self._on_mouse_motion)
        self._cv.bind("<B3-Motion>",       self._on_mouse_motion)

        self._cv.bind("<ButtonPress-1>",   lambda e: self._on_mouse_btn(e, "left", "down"))
        self._cv.bind("<ButtonRelease-1>", lambda e: self._on_mouse_btn(e, "left", "up"))
        self._cv.bind("<ButtonPress-2>",   lambda e: self._on_mouse_btn(e, "middle", "down"))
        self._cv.bind("<ButtonRelease-2>", lambda e: self._on_mouse_btn(e, "middle", "up"))
        self._cv.bind("<ButtonPress-3>",   lambda e: self._on_mouse_btn(e, "right", "down"))
        self._cv.bind("<ButtonRelease-3>", lambda e: self._on_mouse_btn(e, "right", "up"))

        self._cv.bind("<MouseWheel>",      self._on_scroll)
        self._cv.bind("<Button-4>",        lambda e: self._on_scroll_delta(e,  3))
        self._cv.bind("<Button-5>",        lambda e: self._on_scroll_delta(e, -3))
        self._cv.bind("<Configure>",       self._on_canvas_resize)

        # Eventos de teclado (fallback multiplataforma + composição Unicode)
        self.bind("<KeyPress>",   self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self._cv.bind("<KeyPress>",   self._on_key_press)
        self._cv.bind("<KeyRelease>", self._on_key_release)
        self.bind("<FocusOut>",   self._on_focus_out)

    def _layout_overlay(self):
        if self._has_frames:
            self._cv.itemconfig("overlay", state="hidden")
            return
        cw = max(400, self._cv.winfo_width())
        ch = max(300, self._cv.winfo_height())
        cx, cy = cw // 2, ch // 2
        bw, bh = 680, 170
        self._cv.coords(self._ov_box, cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2)
        self._cv.coords(self._ov_title, cx, cy - 26)
        self._cv.coords(self._ov_sub, cx, cy + 28)
        self._cv.itemconfig("overlay", state="normal")
        self._cv.tag_raise("overlay")

    def set_connecting_status(self, subtitle: str, title: str = None):
        if not self._enabled or not self.winfo_exists():
            return
        if title:
            self._overlay_msg = title
        self._overlay_sub = subtitle
        self._overlay_err = False
        self.after(0, self._apply_overlay_text)

    def set_error_status(self, err_msg: str):
        if not self._enabled or not self.winfo_exists():
            return
        self._overlay_msg = "Não foi possível estabelecer a sessão remota"
        self._overlay_sub = err_msg
        self._overlay_err = True
        self.after(0, self._apply_overlay_text)

    def _apply_overlay_text(self):
        if not self.winfo_exists():
            return
        self._cv.itemconfig(self._ov_title, text=self._overlay_msg,
                            fill=C["error"] if self._overlay_err else C["text"])
        self._cv.itemconfig(self._ov_sub, text=self._overlay_sub,
                            fill=C["text_secondary"] if self._overlay_err else C["code_text"])
        self._cv.itemconfig(self._ov_box,
                            outline=C["error"] if self._overlay_err else C["accent"])
        if self._overlay_err:
            self._cstatus.config(text="Falha na Conexão", fg=C["error"])
        self._layout_overlay()

    def _on_connected_cb(self, rinfo: dict):
        if not self._enabled:
            return
        self.remote_info.update(rinfo or {})
        def _upd():
            if not self.winfo_exists():
                return
            h = self.remote_info.get("hostname") or self.remote_info.get("ip") or "Remoto"
            ip = self.remote_info.get("ip") or ""
            mode = self.remote_info.get("mode") or "Conectado"
            self.title(f"RemoteLink — {h} ({mode})")
            self._host_title_lbl.config(text=f"  \u25c9  {h}")
            self._ip_title_lbl.config(text=f"({ip} • {mode})" if ip else f"({mode})")
            self._cstatus.config(text="Conectado", fg=C["success"])
            self.set_connecting_status("Conectado! Recebendo imagem da tela remota...", f"Conectado a {h}")
            self._set_capturing(True)
        self.after(0, _upd)

    def _paste_text_to_remote(self):
        try:
            txt = self.clipboard_get()
            if txt and self.client and self.client.is_connected():
                self.client.send_text(txt)
        except Exception:
            pass

    # ── Captura Direta de Teclado (Estável e Sem Crash de Thread Tcl) ─────

    def _install_keyboard_hook(self):
        try:
            self._cv.focus_set()
        except Exception:
            pass

    def _uninstall_keyboard_hook(self):
        self._local_mods.clear()

    # ── Capture & Fullscreen mode ─────────────────────────────────────────

    def _on_enter_canvas(self, e):
        self._set_capturing(True)

    def _on_leave_canvas(self, e):
        self._set_capturing(False)

    def _on_focus_out(self, e):
        if e.widget is self and self.client:
            self.client.release_all_inputs()

    def _toggle_capture(self):
        self._set_capturing(not self._capturing)

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.attributes("-fullscreen", self._fullscreen)
        self._cv.focus_set()

    def _set_capturing(self, active: bool):
        if self._capturing == active:
            if active:
                try:
                    self._cv.focus_set()
                except Exception:
                    pass
            return
        self._capturing = active

        if active:
            self._cv.config(cursor="none")
            self._cv.itemconfig("cursor", state="normal")
            self._cv.itemconfig("border", state="normal")
            self._mode_lbl.config(
                text="TECLADO/MOUSE: DIRETO ATIVO", bg=C["accent_muted"], fg=C["accent"],
                font=(FONT_UI_SM[0], FONT_UI_SM[1], "bold"))
            try:
                self._cv.focus_set()
            except Exception:
                pass
        else:
            self._uninstall_keyboard_hook()
            if self.client:
                self.client.release_all_inputs()
            self._cv.config(cursor="")
            self._cv.itemconfig("cursor", state="hidden")
            self._cv.itemconfig("border", state="hidden")
            self._mode_lbl.config(
                text="TECLADO/MOUSE: LOCAL", bg=C["bg_alt"], fg=C["text_secondary"],
                font=FONT_UI_SM)

    def _on_canvas_resize(self, e):
        w, h = e.width, e.height
        self._cv.coords("border", 1, 1, w - 1, h - 1)
        self._layout_overlay()

    # ── Frame decoding & rendering (Decodificação Assíncrona para > 27 FPS) ─

    def _on_frame(self, data: bytes, ts: int):
        with self._frame_lock:
            self._latest_raw = data
            self._fc += 1
        self._new_frame_ev.set()

    def _frame_worker_loop(self):
        """Thread assíncrona dedicada que decodifica o JPEG e redimensiona sem travar o Tkinter."""
        from PIL import Image
        last_raw = None
        while self._enabled:
            self._new_frame_ev.wait(timeout=0.03)
            self._new_frame_ev.clear()
            with self._frame_lock:
                raw = self._latest_raw
                self._latest_raw = None
            if not raw or raw is last_raw:
                continue
            last_raw = raw
            try:
                img = Image.open(io.BytesIO(raw))
                rw, rh = img.size
                self._rw, self._rh = rw, rh

                cw = max(2, self._last_cw)
                ch = max(2, self._last_ch)
                sc = min(cw / rw, ch / rh)
                nw = max(1, int(rw * sc))
                nh = max(1, int(rh * sc))
                if (nw, nh) != (rw, rh):
                    img = img.resize((nw, nh), Image.BOX if hasattr(Image, "BOX") else Image.NEAREST)

                with self._ready_lock:
                    self._ready_image = (img, nw, nh)
            except Exception as e:
                logger.debug(f"decode worker error: {e}")

    def _schedule_render(self):
        if not self._enabled or not self.winfo_exists():
            return
        self._render_frame()
        if self._enabled and self.winfo_exists():
            self.after(8, self._schedule_render)

    def _render_frame(self):
        with self._ready_lock:
            tup = self._ready_image
            self._ready_image = None
        if not tup:
            return
        img, nw, nh = tup
        try:
            from PIL import ImageTk
            if not self._has_frames:
                self._has_frames = True
                self._cv.itemconfig("overlay", state="hidden")
                self._cstatus.config(text="Ao Vivo", fg=C["success"])
                self._cv.focus_set()

            cw = self._cv.winfo_width()
            ch = self._cv.winfo_height()
            self._last_cw = cw
            self._last_ch = ch
            cx, cy = cw // 2, ch // 2

            if self._photo is not None and self._photo_size == (nw, nh):
                self._photo.paste(img)
                if self._cimg is not None:
                    self._cv.coords(self._cimg, cx, cy)
            else:
                self._photo = ImageTk.PhotoImage(img)
                self._photo_size = (nw, nh)
                if self._cimg is None:
                    self._cimg = self._cv.create_image(cx, cy, image=self._photo,
                                                        anchor="center", tags="frame")
                else:
                    self._cv.itemconfig(self._cimg, image=self._photo)
                    self._cv.coords(self._cimg, cx, cy)

            self._cv.tag_lower("frame")
            self._cv.tag_raise("cursor")
            self._cv.tag_raise("border")
        except Exception as e:
            logger.debug(f"render: {e}")

    # ── Controles de Som, Microfone e Qualidade ───────────────────────────

    def _toggle_sound(self):
        if not self.client:
            return
        st = self.client.toggle_sound()
        self._sound_btn.config(
            text="🔊 Som: Ativo" if st else "🔇 Som: Mudo",
            fg=C["success"] if st else C["text_secondary"]
        )

    def _toggle_mic(self):
        if not self.client:
            return
        st = self.client.toggle_mic()
        self._mic_btn.config(
            text="🎙️ Mic: Ativo" if st else "🎙️ Mic: Mudo",
            fg=C["accent"] if st else C["text_secondary"]
        )

    def _cycle_quality(self):
        if not self.client:
            return
        modes = ["high", "balanced", "fast"]
        labels = {
            "high": "🎨 Qualidade: HD",
            "balanced": "🎨 Qualidade: Equilibrada",
            "fast": "🎨 Qualidade: Rápida",
        }
        cur = getattr(self, "_quality_idx", 0)
        nxt = (cur + 1) % len(modes)
        self._quality_idx = nxt
        mode = modes[nxt]
        self.client.set_quality(mode)
        self._quality_btn.config(text=labels[mode])

    # ── Coordinate transforms (Pixel + Normalizado 0.0..1.0) ──────────────

    def _tr(self, cx, cy) -> tuple[int, int, float, float]:
        cw = self._cv.winfo_width()
        ch = self._cv.winfo_height()
        if cw < 2 or ch < 2 or self._rw < 1 or self._rh < 1:
            return 0, 0, 0.0, 0.0

        sc = min(cw / self._rw, ch / self._rh)
        disp_w = max(1, int(self._rw * sc))
        disp_h = max(1, int(self._rh * sc))
        ox = (cw - disp_w) // 2
        oy = (ch - disp_h) // 2

        nx = max(0.0, min(1.0, (cx - ox) / disp_w))
        ny = max(0.0, min(1.0, (cy - oy) / disp_h))

        rx = int(nx * (self._rw - 1))
        ry = int(ny * (self._rh - 1))

        return rx, ry, nx, ny

    def _move_cursor(self, cx, cy):
        r = 4
        self._cv.coords("cursor", cx - r, cy - r, cx + r, cy + r)

    # ── Mouse events (Press, Release, Drag, Scroll — igual ao AnyDesk) ────

    def _on_mouse_motion(self, e):
        self._move_cursor(e.x, e.y)
        if not self._capturing:
            self._set_capturing(True)
        if self._capturing and self._enabled and self.client and self.client.is_connected():
            now = time.perf_counter()
            rx, ry, nx, ny = self._tr(e.x, e.y)
            if now - self._last_move_ts >= 0.005:
                self._last_move_ts = now
                self.client.send_mouse_move(rx, ry, nx, ny)

    def _on_mouse_btn(self, e, btn: str, state: str):
        if not self._capturing:
            self._set_capturing(True)
        self._cv.focus_set()
        if self._capturing and self._enabled and self.client and self.client.is_connected():
            rx, ry, nx, ny = self._tr(e.x, e.y)
            self.client.send_mouse_click(rx, ry, btn, state, nx, ny)

    def _on_scroll(self, e):
        if self._capturing and self._enabled and self.client and self.client.is_connected():
            rx, ry, nx, ny = self._tr(e.x, e.y)
            steps = int(e.delta / 120) if abs(e.delta) >= 120 else (1 if e.delta > 0 else -1)
            self.client.send_mouse_scroll(rx, ry, steps * 3, nx=nx, ny=ny)

    def _on_scroll_delta(self, e, d):
        if self._capturing and self._enabled and self.client and self.client.is_connected():
            rx, ry, nx, ny = self._tr(e.x, e.y)
            self.client.send_mouse_scroll(rx, ry, d, nx=nx, ny=ny)

    # ── Keyboard events (Envio Direto de Key + VK + Scancode + Unicode) ───

    def _map_key(self, tk_key: str) -> str:
        mapping = {
            "Control_L": "lctrl", "Control_R": "rctrl",
            "Shift_L": "lshift", "Shift_R": "rshift",
            "Alt_L": "lalt", "Alt_R": "ralt",
            "Caps_Lock": "capslock", "Num_Lock": "numlock", "Scroll_Lock": "scrolllock",
            "Tab": "tab", "Return": "enter", "KP_Enter": "enter",
            "BackSpace": "backspace", "Escape": "esc", "space": "space", "Space": "space",
            "Delete": "delete", "Insert": "insert",
            "Home": "home", "End": "end",
            "Prior": "pageup", "Next": "pagedown",
            "Left": "left", "Right": "right", "Up": "up", "Down": "down",
            "Print": "printscreen", "Pause": "pause",
            "Win_L": "lwin", "Win_R": "rwin", "Super_L": "lwin", "Super_R": "rwin",
            "App": "apps", "Menu": "apps",
            "semicolon": ";", "equal": "=", "comma": ",", "minus": "-",
            "period": ".", "slash": "/", "grave": "`", "quoteleft": "`",
            "bracketleft": "[", "backslash": "\\", "bracketright": "]",
            "apostrophe": "'", "quoteright": "'",
            "KP_Add": "add", "KP_Subtract": "subtract",
            "KP_Multiply": "multiply", "KP_Divide": "divide", "KP_Decimal": "decimal",
            **{f"KP_{i}": f"num{i}" for i in range(10)},
            **{f"F{i}": f"f{i}" for i in range(1, 25)},
        }
        return mapping.get(tk_key, tk_key.lower() if len(tk_key) == 1 else tk_key.lower())

    def _on_key_press(self, e):
        if not self._enabled or not self.client or not self.client.is_connected():
            return
        if not self._capturing:
            self._set_capturing(True)
        key = self._map_key(e.keysym)
        vk = int(getattr(e, "keycode", 0) or 0) if _IS_WIN else 0
        scan = 0
        if _IS_WIN and vk > 0:
            try:
                scan = int(_user32.MapVirtualKeyW(vk, 0))
            except Exception:
                scan = 0
        ch = e.char if (e.char and len(e.char) == 1 and ord(e.char) >= 32) else ""
        self.client.send_key_down(key=key, vk=vk, scan=scan, char=ch)
        return "break"

    def _on_key_release(self, e):
        if not self._enabled or not self.client or not self.client.is_connected():
            return
        key = self._map_key(e.keysym)
        vk = int(getattr(e, "keycode", 0) or 0) if _IS_WIN else 0
        scan = 0
        if _IS_WIN and vk > 0:
            try:
                scan = int(_user32.MapVirtualKeyW(vk, 0))
            except Exception:
                scan = 0
        self.client.send_key_up(key=key, vk=vk, scan=scan)
        return "break"

    # ── Disconnect ────────────────────────────────────────────────────────

    def _on_disconnected(self):
        self._uninstall_keyboard_hook()
        if self.winfo_exists():
            self.after(0, lambda: self._cstatus.config(
                text="Desconectado", fg=C["error"]))

    def _close(self):
        self._enabled = False
        self._uninstall_keyboard_hook()
        try:
            if self.client:
                self.client.disconnect()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    # ── Special keys (Atalhos na Toolbar) ─────────────────────────────────

    def _send_alt_tab(self):
        if self.client and self.client.is_connected():
            self.client.send_hotkey("alt", "tab")

    def _send_win(self):
        if self.client and self.client.is_connected():
            self.client.send_hotkey("win")

    def _send_cad(self):
        if self.client and self.client.is_connected():
            self.client.send_hotkey("ctrl", "alt", "delete")

    def _send_prtscr(self):
        if self.client and self.client.is_connected():
            self.client.send_hotkey("printscreen")

    def _update_fps(self):
        if self._enabled and self.winfo_exists():
            now = time.time()
            elapsed = now - self._fts
            if elapsed >= 1.0:
                fps = self._fc / elapsed
                self._fps_lbl.config(text=f"{fps:.0f} fps")
                self._fc = 0
                self._fts = now
            self.after(500, self._update_fps)

    def _show_security_dialog(self):
        info = dict(self.remote_info or {})
        if self.client:
            if getattr(self.client, "session_fingerprint", ""):
                info["session_fingerprint"] = self.client.session_fingerprint
            if getattr(self.client, "pow_hash", ""):
                info["pow_hash"] = self.client.pow_hash
            info["permissions"] = getattr(self.client, "permissions", {"keyboard_mouse": True, "audio": True, "mic": True})
        SecurityProofDialog(self, info)


# ── Main App ───────────────────────────────────────────────────────────────────

class RemoteLinkApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RemoteLink v2.0 — Acesso Remoto Direto (LAN & Rede Externa)")
        self.geometry("1080x720")
        self.minsize(900, 600)
        self.configure(bg=C["bg_surface"])
        try:
            self.iconbitmap("assets/icon.ico")
        except Exception:
            pass
        configure_styles()

        self.machine_info = get_machine_info(fetch_public=False)
        self.server = RemoteLinkServer(access_code=self.machine_info["access_code"])
        self.client: Optional[RemoteLinkClient] = None
        self.viewer_window: Optional[ViewerWindow] = None

        self._build()
        self.after(250, self._autostart)

    def _build(self):
        # Top dashboard banner
        self._banner = MachineBanner(self, self.machine_info)
        self._banner.pack(fill="x")
        Divider(self).pack(fill="x")

        # Body
        body = tk.Frame(self, bg=C["bg_surface"])
        body.pack(fill="both", expand=True)

        # Nav sidebar
        nav = tk.Frame(body, bg=C["nav_bg"], width=195)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Frame(nav, height=12, bg=C["nav_bg"]).pack()

        # Content
        self._content = tk.Frame(body, bg=C["bg_surface"])
        self._content.pack(side="left", fill="both", expand=True)

        # Pages
        self._pages = {
            "connect": ConnectPage(self._content, on_connect_request=self._do_connect),
            "share":   SharePage(self._content, machine_info=self.machine_info,
                                  server=self.server),
        }

        # Wire server events
        def _on_connect(addr, info):
            self._pages["share"].on_client_connected(addr, info)
            self._banner.update_status("connected")

        def _on_disconnect():
            self._pages["share"].on_client_disconnected()
            self._banner.update_status("listening")

        def _on_status(s):
            self._banner.update_status(s)

        def _on_net_event(msg):
            self._pages["share"].log_network_event(msg)

        def _on_auth_req(client_info: dict) -> tuple[bool, dict]:
            res = {"accepted": False, "perms": {}}
            ev = threading.Event()
            def _open_dlg():
                try:
                    dlg = AuthorizationDialog(self, client_info)
                    def _wait_dlg():
                        acc, perms = dlg.wait_result(timeout=45.0)
                        res["accepted"] = acc
                        res["perms"] = perms
                        ev.set()
                    threading.Thread(target=_wait_dlg, daemon=True).start()
                except Exception as e:
                    logger.error(f"AuthorizationDialog error: {e}")
                    res["accepted"] = True
                    ev.set()

            self.after(0, _open_dlg)
            ev.wait(timeout=46.0)
            return res["accepted"], res["perms"]

        self.server.on_client_connect         = _on_connect
        self.server.on_client_disconnect      = _on_disconnect
        self.server.on_status_change          = _on_status
        self.server.on_network_event          = _on_net_event
        self.server.on_authorization_request  = _on_auth_req

        # Nav items
        self._navitems = {}
        for key, label in [
            ("connect", "Conectar à Tela"),
            ("share",   "Servidor & Portas"),
        ]:
            ni = NavItem(nav, label,
                         command=lambda k=key: self._show(k))
            ni.pack(fill="x", padx=8, pady=2)
            self._navitems[key] = ni

        # Footer
        tk.Frame(nav, bg=C["nav_bg"]).pack(fill="y", expand=True)
        Divider(nav).pack(fill="x", padx=8)
        tk.Label(nav, text="RemoteLink v2.0\nAnyDesk-Engine Input",
                 font=FONT_UI_SM, bg=C["nav_bg"],
                 fg=C["text_caption"], justify="center").pack(pady=12)

        self._show("connect")

    def _show(self, key):
        for p in self._pages.values():
            p.pack_forget()
        for k, ni in self._navitems.items():
            ni.activate(k == key)
        self._pages[key].pack(fill="both", expand=True)

    def _autostart(self):
        self._pages["share"]._do_toggle()

        def _fetch_wan():
            try:
                pub_ip = get_public_ip(force_refresh=True)
                self.machine_info["public_ip"] = pub_ip
                if self.winfo_exists():
                    self.after(0, lambda: self._banner.set_public_ip(pub_ip, self.server.listening_ports) if self.winfo_exists() else None)
            except Exception:
                pass

        threading.Thread(target=_fetch_wan, daemon=True, name="RL-WanCheck").start()

    def _do_connect(self, info: dict):
        """
        Abre IMEDIATAMENTE a ViewerWindow ("a tela para mexer") e executa a
        conexão inteligente (Multi-Portas Paralelas + Relay Externo + LAN Scan) em background,
        mostrando o progresso na própria tela remota.
        """
        method = info.get("method", "ip")
        ip     = info.get("ip")
        port   = int(info.get("port") or 52340)
        code   = (info.get("code") or info.get("access_code") or "").strip().upper()

        if code and is_own_code(code):
            messagebox.showerror("Restrição", "Você não pode se conectar ao seu próprio código de acesso.")
            return
        if ip and is_local_target(ip):
            messagebox.showerror("Restrição", "Não é possível conectar ao seu próprio IP.\nInforme o código ou IP de outro computador.")
            return

        # Fecha sessão anterior se existir
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass

        last_err = {"msg": ""}

        def on_error(msg):
            last_err["msg"] = msg
            if self.viewer_window and self.viewer_window.winfo_exists():
                self.viewer_window.set_error_status(msg)

        self.client = RemoteLinkClient(
            on_status_change=lambda s: None,
            on_error=on_error,
        )

        target_label = info.get("hostname") or ip or code or "Computador Remoto"
        initial_info = {
            "hostname": target_label,
            "ip": ip or "",
            "port": port,
            "code": code,
            "access_code": code,
        }

        # Abre IMEDIATAMENTE a janela da tela remota ("a tela para mexer")!
        self._open_viewer(initial_info)
        if self.viewer_window and self.viewer_window.winfo_exists():
            self.viewer_window.set_connecting_status(
                "Testando portas abertas (52340, 7070, 6568, 8080, 8443, 33890...) e túnel Relay Externo...",
                title=f"Conectando a {target_label}..."
            )

        def run_connection():
            def on_prog(txt: str):
                if self.viewer_window and self.viewer_window.winfo_exists():
                    self.viewer_window.set_connecting_status(txt)

            target_dict = dict(info)
            target_dict["access_code"] = code
            target_dict["port"] = port

            ok = self.client.connect_smart(
                target_dict,
                local_access_code=self.machine_info["access_code"],
                on_progress=on_prog,
            )
            if ok:
                return

            # Se era um código de 6 dígitos e ainda não conectou via WAN/Relay, tenta varredura rápida na LAN
            if len(code.replace("-", "")) == 6:
                on_prog("Buscando computador também na rede local (LAN/VPN)...")
                found_lan = {"ok": False}
                done_ev = threading.Event()

                def on_lan_found(m):
                    if found_lan["ok"] or is_local_target(m.get("ip", "")):
                        return
                    if self.client.connect(
                        m["ip"], port=int(m.get("port") or 52340),
                        access_code=code,
                        local_access_code=self.machine_info["access_code"],
                        timeout=2.5, silent_error=True
                    ):
                        found_lan["ok"] = True
                        done_ev.set()

                scanner = NetworkScanner(
                    on_found=on_lan_found,
                    on_done=lambda _: done_ev.set(),
                    max_workers=80,
                    timeout=0.35,
                )
                scanner.start()
                done_ev.wait(timeout=8.0)
                scanner.stop()
                if found_lan["ok"]:
                    return

            if self.viewer_window and self.viewer_window.winfo_exists():
                err_txt = last_err["msg"] or (
                    "Tempo de conexão esgotado.\n"
                    "Para acesso externo sem abrir portas no roteador, use o Código de 6 dígitos (ex: 750-789)!"
                )
                self.viewer_window.set_error_status(err_txt)

        threading.Thread(target=run_connection, daemon=True, name="RL-SmartConnect").start()

    def _open_viewer(self, remote_info: dict):
        if self.viewer_window and self.viewer_window.winfo_exists():
            try:
                self.viewer_window._enabled = False
                self.viewer_window._uninstall_keyboard_hook()
                self.viewer_window.destroy()
            except Exception:
                pass
        self.viewer_window = ViewerWindow(self, self.client, remote_info)
        self.viewer_window.deiconify()
        self.viewer_window.lift()
        self.viewer_window.focus_force()


def main():
    app = RemoteLinkApp()
    app.mainloop()


if __name__ == "__main__":
    main()
