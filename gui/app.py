"""
RemoteLink - GUI Application
Windows 11 Fluent Design aesthetic
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import sys
import os
import io
import logging
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.identity import get_machine_info, resolve_target, scan_local_network
from core.client import RemoteLinkClient, probe_target
from core.server import RemoteLinkServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remotelink.gui")

# ── Windows 11 Fluent Color System ────────────────────────────────────────────
C = {
    "surface":         "#F3F3F3",
    "surface_alt":     "#EBEBEB",
    "surface_card":    "#FFFFFF",
    "surface_smoke":   "#F9F9F9",
    "nav_bg":          "#E8E8E8",
    "nav_hover":       "#DBDBDB",
    "nav_active":      "#FFFFFF",
    "nav_active_bar":  "#0067C0",
    "titlebar":        "#F3F3F3",
    "border":          "#E0E0E0",
    "border_strong":   "#C8C8C8",
    "border_focus":    "#0067C0",
    "accent":          "#0067C0",
    "accent_light":    "#0078D4",
    "accent_hover":    "#006CBE",
    "accent_pressed":  "#005BA1",
    "accent_subtle":   "#EEF4FB",
    "accent_text":     "#003E8A",
    "success":         "#0F7B0F",
    "success_bg":      "#DFF6DD",
    "warning":         "#9D5D00",
    "warning_bg":      "#FFF4CE",
    "error":           "#C42B1C",
    "error_bg":        "#FDE7E9",
    "error_hover":     "#B52617",
    "text":            "#1A1A1A",
    "text_secondary":  "#5C5C5C",
    "text_disabled":   "#A0A0A0",
    "text_on_accent":  "#FFFFFF",
    "text_caption":    "#767676",
    "ctrl_fill":       "#FBFBFB",
    "ctrl_fill_hover": "#F5F5F5",
    "ctrl_fill_press": "#EFEFEF",
    "ctrl_stroke":     "#C6C6C6",
    "code_bg":         "#F0F4F8",
    "code_text":       "#0F4C81",
}

# ── Fonts ─────────────────────────────────────────────────────────────────────
import tkinter.font as tkfont

_UI_FAMS   = ["Segoe UI Variable", "Segoe UI", "Helvetica Neue", "Arial"]
_MONO_FAMS = ["Cascadia Code", "Cascadia Mono", "Consolas", "Courier New"]

def _f(fams, size, bold=False):
    available = tkfont.families()
    for name in fams:
        if name in available:
            return (name, size, "bold") if bold else (name, size)
    return (fams[-1], size, "bold") if bold else (fams[-1], size)

# Resolved at runtime after Tk is created
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
    FONT_CODE_XL  = _f(_MONO_FAMS, 22, bold=True)


def configure_styles():
    _setup_fonts()
    s = ttk.Style()
    s.theme_use("clam")
    BG = C["surface"]

    s.configure("TFrame",      background=BG)
    s.configure("Nav.TFrame",  background=C["nav_bg"])
    s.configure("Card.TFrame", background=C["surface_card"])
    s.configure("Smoke.TFrame",background=C["surface_smoke"])

    s.configure("TLabel",
        background=BG, foreground=C["text"], font=FONT_UI)
    s.configure("Secondary.TLabel",
        background=BG, foreground=C["text_secondary"], font=FONT_UI_SM)
    s.configure("Caption.TLabel",
        background=BG, foreground=C["text_caption"], font=FONT_UI_SM)
    s.configure("Card.TLabel",
        background=C["surface_card"], foreground=C["text"], font=FONT_UI)
    s.configure("Card.Secondary.TLabel",
        background=C["surface_card"], foreground=C["text_secondary"], font=FONT_UI_SM)

    s.configure("TButton",
        background=C["ctrl_fill"], foreground=C["text"],
        font=FONT_UI, relief="flat", borderwidth=1,
        bordercolor=C["ctrl_stroke"], padding=(14, 6))
    s.map("TButton",
        background=[("active", C["ctrl_fill_hover"]),
                    ("pressed", C["ctrl_fill_press"])])

    s.configure("Accent.TButton",
        background=C["accent_light"], foreground=C["text_on_accent"],
        font=FONT_UI_BODY_B, relief="flat", borderwidth=0, padding=(16, 7))
    s.map("Accent.TButton",
        background=[("active", C["accent_hover"]),
                    ("pressed", C["accent_pressed"])])

    s.configure("Danger.TButton",
        background=C["error"], foreground=C["text_on_accent"],
        font=FONT_UI_BODY_B, relief="flat", borderwidth=0, padding=(14, 6))
    s.map("Danger.TButton",
        background=[("active", C["error_hover"])])

    s.configure("Success.TButton",
        background=C["success"], foreground=C["text_on_accent"],
        font=FONT_UI_BODY_B, relief="flat", borderwidth=0, padding=(14, 6))
    s.map("Success.TButton",
        background=[("active", "#0A6A0A")])

    s.configure("TSeparator",   background=C["border"])
    s.configure("TScrollbar",
        background=C["surface_alt"], troughcolor=C["surface"],
        borderwidth=0, arrowsize=0, width=6)
    s.map("TScrollbar",
        background=[("active", C["border_strong"])])

    s.configure("Treeview",
        background=C["surface_card"], foreground=C["text"],
        fieldbackground=C["surface_card"], borderwidth=0,
        font=FONT_UI, rowheight=34)
    s.configure("Treeview.Heading",
        background=C["surface_smoke"], foreground=C["text_secondary"],
        font=FONT_UI_SM, borderwidth=0, relief="flat")
    s.map("Treeview",
        background=[("selected", C["accent_subtle"])],
        foreground=[("selected", C["accent_text"])])

    s.configure("Horizontal.TProgressbar",
        background=C["accent_light"], troughcolor=C["surface_alt"],
        borderwidth=0, thickness=3)


# ── Base UI Helpers ────────────────────────────────────────────────────────────

class Divider(tk.Frame):
    def __init__(self, parent, color=None, vertical=False, **kw):
        if vertical:
            super().__init__(parent, width=1, bg=color or C["border"], **kw)
        else:
            super().__init__(parent, height=1, bg=color or C["border"], **kw)


class CardFrame(tk.Frame):
    """Elevated white card with border."""
    def __init__(self, parent, padding=16, **kw):
        super().__init__(parent,
            bg=C["surface_card"],
            highlightbackground=C["border"],
            highlightthickness=1, **kw)
        self.inner = tk.Frame(self, bg=C["surface_card"])
        self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)


class SectionHeader(tk.Frame):
    def __init__(self, parent, title, subtitle=None, bg=None, **kw):
        bg = bg or C["surface"]
        super().__init__(parent, bg=bg, **kw)
        tk.Label(self, text=title, font=FONT_UI_SUBH,
                 bg=bg, fg=C["text"]).pack(anchor="w")
        if subtitle:
            tk.Label(self, text=subtitle, font=FONT_UI_SM,
                     bg=bg, fg=C["text_secondary"],
                     wraplength=500, justify="left").pack(anchor="w", pady=(2, 0))


class FlatBtn(tk.Button):
    """Flat button with Windows 11 look."""
    _PRESETS = {
        "default": dict(bg=C["ctrl_fill"], fg=C["text"],
                        abg=C["ctrl_fill_hover"], afg=C["text"],
                        hl=C["ctrl_stroke"], hlt=1, px=14, py=6),
        "accent":  dict(bg=C["accent_light"], fg=C["text_on_accent"],
                        abg=C["accent_hover"], afg=C["text_on_accent"],
                        hl="", hlt=0, px=16, py=7),
        "danger":  dict(bg=C["error"], fg=C["text_on_accent"],
                        abg=C["error_hover"], afg=C["text_on_accent"],
                        hl="", hlt=0, px=14, py=6),
        "success": dict(bg=C["success"], fg=C["text_on_accent"],
                        abg="#0A6A0A", afg=C["text_on_accent"],
                        hl="", hlt=0, px=14, py=6),
        "subtle":  dict(bg=C["surface"], fg=C["text_secondary"],
                        abg=C["surface_alt"], afg=C["text"],
                        hl="", hlt=0, px=10, py=5),
        "nav_subtle": dict(bg=C["nav_bg"], fg=C["text_secondary"],
                        abg=C["nav_hover"], afg=C["text"],
                        hl="", hlt=0, px=10, py=5),
    }

    def __init__(self, parent, text="", icon="", variant="default",
                 command=None, **kw):
        label = f"{icon}  {text}".strip() if icon else text
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
        "info":    (C["accent_subtle"], C["accent_text"]),
        "neutral": (C["surface_alt"], C["text_secondary"]),
    }
    def __init__(self, parent, text, preset="info", **kw):
        bg, fg = self._P.get(preset, self._P["neutral"])
        super().__init__(parent, text=text, bg=bg, fg=fg,
                         font=FONT_UI_SM, padx=8, pady=2, **kw)


class StatusDot(tk.Frame):
    """Animated dot + label like Windows 11 Settings status."""
    def __init__(self, parent, bg=None, **kw):
        bg = bg or C["surface"]
        super().__init__(parent, bg=bg, **kw)
        self._bg = bg
        self._dot = tk.Label(self, text="●", font=_f(_UI_FAMS, 10),
                             bg=bg, fg=C["text_disabled"])
        self._dot.pack(side="left", padx=(0, 5))
        self._lbl = tk.Label(self, text="—", font=FONT_UI,
                             bg=bg, fg=C["text_secondary"])
        self._lbl.pack(side="left")
        self._pid = None

    def set(self, status: str, text: str = None):
        colors = {
            "online": C["success"], "connected": C["success"],
            "listening": C["accent_light"], "connecting": C["warning"],
            "disconnected": C["text_disabled"], "error": C["error"],
            "stopped": C["text_disabled"],
        }
        texts = {
            "online": "Online", "connected": "Conectado",
            "listening": "Aguardando conexões", "connecting": "Conectando…",
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
    """Left-nav item with Windows 11 active pill."""
    def __init__(self, parent, icon, label, command, **kw):
        super().__init__(parent, bg=C["nav_bg"], cursor="hand2", **kw)
        self._cmd = command
        self._active = False

        # Active bar
        self._bar = tk.Frame(self, width=3, bg=C["nav_bg"])
        self._bar.pack(side="left", fill="y", pady=4)

        # Inner
        self._inner = tk.Frame(self, bg=C["nav_bg"])
        self._inner.pack(side="left", fill="both", expand=True, padx=(6, 14), pady=9)

        self._icon = tk.Label(self._inner, text=icon,
                              font=_f(_UI_FAMS, 13), bg=C["nav_bg"], fg=C["text"])
        self._icon.pack(side="left", padx=(0, 9))

        self._text = tk.Label(self._inner, text=label,
                              font=FONT_UI, bg=C["nav_bg"], fg=C["text"])
        self._text.pack(side="left")

        for w in (self, self._inner, self._icon, self._text, self._bar):
            w.bind("<Button-1>", lambda e: self._cmd() if self._cmd else None)
        for w in (self, self._inner, self._icon, self._text):
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)

    def activate(self, on: bool):
        self._active = on
        bg = C["nav_active"] if on else C["nav_bg"]
        bar_bg = C["nav_active_bar"] if on else C["nav_bg"]
        self._bar.config(bg=bar_bg)
        for w in (self, self._inner, self._icon, self._text):
            w.config(bg=bg)

    def _hover_on(self, e=None):
        if not self._active:
            for w in (self, self._inner, self._icon, self._text):
                w.config(bg=C["nav_hover"])

    def _hover_off(self, e=None):
        if not self._active:
            for w in (self, self._inner, self._icon, self._text):
                w.config(bg=C["nav_bg"])


# ── Connection Preview Panel ───────────────────────────────────────────────────

class ConnectionPreview(tk.Frame):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["surface"])
        super().__init__(parent, **kw)
        self._cb = None
        self._info = None
        self._aid = None
        self._ai = 0
        self._build()

    def _build(self):
        card = tk.Frame(self, bg=C["surface_card"],
                        highlightbackground=C["border"], highlightthickness=1)
        card.pack(fill="x", pady=(8, 0))

        # Header
        hdr = tk.Frame(card, bg=C["surface_smoke"])
        hdr.pack(fill="x")
        self._title = tk.Label(hdr, text="Verificando…",
            font=FONT_UI_BODY_B, bg=C["surface_smoke"], fg=C["text"],
            padx=16, pady=10, anchor="w")
        self._title.pack(side="left", fill="x", expand=True)
        tk.Button(hdr, text="✕", font=FONT_UI_SM,
            bg=C["surface_smoke"], fg=C["text_secondary"],
            activebackground=C["surface_alt"], activeforeground=C["error"],
            relief="flat", cursor="hand2", padx=12, pady=8,
            command=self.hide).pack(side="right")
        Divider(card).pack(fill="x")

        body = tk.Frame(card, bg=C["surface_card"])
        body.pack(fill="x", padx=20, pady=16)

        # Loading
        self._load_f = tk.Frame(body, bg=C["surface_card"])
        self._load_f.pack(fill="x")
        self._spin = tk.Label(self._load_f, text="◌",
            font=_f(_UI_FAMS, 20), bg=C["surface_card"], fg=C["accent_light"])
        self._spin.pack(side="left", padx=(0, 10))
        self._spin_txt = tk.Label(self._load_f, text="Verificando na rede…",
            font=FONT_UI, bg=C["surface_card"], fg=C["text_secondary"])
        self._spin_txt.pack(side="left")

        # Result
        self._res_f = tk.Frame(body, bg=C["surface_card"])

        # Machine header
        mhdr = tk.Frame(self._res_f, bg=C["surface_card"])
        mhdr.pack(fill="x", pady=(0, 12))
        self._os_icon = tk.Label(mhdr, text="🖥", font=_f(_UI_FAMS, 28),
                                  bg=C["surface_card"])
        self._os_icon.pack(side="left", padx=(0, 12))
        nc = tk.Frame(mhdr, bg=C["surface_card"])
        nc.pack(side="left", fill="x", expand=True)
        self._host_lbl = tk.Label(nc, text="—", font=FONT_UI_LG,
                                   bg=C["surface_card"], fg=C["text"], anchor="w")
        self._host_lbl.pack(anchor="w")
        self._plat_lbl = tk.Label(nc, text="—", font=FONT_UI_SM,
                                   bg=C["surface_card"], fg=C["text_secondary"], anchor="w")
        self._plat_lbl.pack(anchor="w", pady=(2, 0))
        self._badge_f = tk.Frame(mhdr, bg=C["surface_card"])
        self._badge_f.pack(side="right", anchor="n", pady=4)

        # Details box
        det_box = tk.Frame(self._res_f, bg=C["surface_smoke"],
                           highlightbackground=C["border"], highlightthickness=1)
        det_box.pack(fill="x", pady=(0, 14))
        det_in = tk.Frame(det_box, bg=C["surface_smoke"])
        det_in.pack(fill="x", padx=14, pady=10)
        self._dvals = {}
        for key, lbl in [("ip","Endereço IP"),("hostname","Hostname"),
                         ("platform","Sistema"),("method","Método")]:
            row = tk.Frame(det_in, bg=C["surface_smoke"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, font=FONT_UI_SM, bg=C["surface_smoke"],
                     fg=C["text_caption"], width=14, anchor="w").pack(side="left")
            v = tk.Label(row, text="—", font=FONT_MONO,
                         bg=C["surface_smoke"], fg=C["text"])
            v.pack(side="left")
            self._dvals[key] = v

        # Buttons
        btn_row = tk.Frame(self._res_f, bg=C["surface_card"])
        btn_row.pack(fill="x")
        self._conn_btn = FlatBtn(btn_row, text="Conectar", icon="→",
                                  variant="accent", command=self._do_connect)
        self._conn_btn.config(font=FONT_UI_BODY_B, state="disabled")
        self._conn_btn.pack(side="right")
        FlatBtn(btn_row, text="Cancelar", variant="default",
                command=self.hide).pack(side="right", padx=(0, 8))

    def show_loading(self, target):
        self.pack(fill="x")
        self._title.config(text=f"Verificando  {target}")
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
            plat += f"  {info['platform_version'][:35]}"

        methods = {"ip":"IP Direto","hostname":"Hostname / DNS",
                   "access_code":"Código de Acesso","scan":"Descoberta Local"}
        osicons = {"windows":"🪟","linux":"🐧","darwin":"🍎"}
        p = (info.get("platform") or "").lower()
        self._os_icon.config(text=osicons.get(
            next((k for k in osicons if k in p), ""), "🖥"))

        self._host_lbl.config(text=hostname)
        self._plat_lbl.config(text=plat or "Sistema Remoto")
        self._dvals["ip"].config(text=info.get("ip") or info.get("local_ip") or "—")
        self._dvals["hostname"].config(text=hostname)
        self._dvals["platform"].config(text=plat or "—")
        self._dvals["method"].config(
            text=methods.get(info.get("method",""), info.get("method","—")))

        for w in self._badge_f.winfo_children():
            w.destroy()

        if reachable:
            self._title.config(text="Máquina encontrada — pronta para conectar")
            Badge(self._badge_f, "● Online", "success").pack()
            self._conn_btn.config(bg=C["accent_light"], state="normal",
                                  text="  Conectar  →")
        else:
            self._title.config(text="Máquina não alcançável")
            Badge(self._badge_f, "● Offline", "error").pack()
            self._conn_btn.config(bg=C["text_disabled"], state="disabled",
                                  text="  Inacessível")

    def hide(self):
        if self._aid:
            self.after_cancel(self._aid)
        self.pack_forget()

    def _do_connect(self):
        if self._cb and self._info:
            self._cb(self._info)

    _SPIN = ["◌","◎","●","◎"]
    def _animate(self):
        self._ai = (self._ai + 1) % 4
        try:
            self._spin.config(text=self._SPIN[self._ai])
            self._aid = self.after(250, self._animate)
        except Exception:
            pass


# ── Connect Page ───────────────────────────────────────────────────────────────

class ConnectPage(tk.Frame):
    _PH = "Código, IP ou Hostname  —  ex: ABC-DEF-GHI"

    def __init__(self, parent, on_connect_request, **kw):
        kw.setdefault("bg", C["surface"])
        super().__init__(parent, **kw)
        self._on_connect = on_connect_request
        self._build()

    def _build(self):
        # Scrollable container
        canvas = tk.Canvas(self, bg=C["surface"], highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        sf = tk.Frame(canvas, bg=C["surface"])
        wid = canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        sf.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1*(e.delta/120)), "units"))

        pad = tk.Frame(sf, bg=C["surface"])
        pad.pack(fill="both", expand=True, padx=32, pady=28)

        # Title
        SectionHeader(pad,
            title="Conectar a um computador remoto",
            subtitle="Digite o código de acesso, hostname ou IP do computador que deseja controlar",
        ).pack(anchor="w", pady=(0, 20))

        # ── Input card ────────────────────────────────────────────────────
        ic = CardFrame(pad, padding=20)
        ic.pack(fill="x", pady=(0, 4))

        tk.Label(ic.inner, text="Endereço do computador",
                 font=FONT_UI_BODY_B, bg=C["surface_card"],
                 fg=C["text"]).pack(anchor="w", pady=(0, 8))

        row = tk.Frame(ic.inner, bg=C["surface_card"])
        row.pack(fill="x", pady=(0, 10))

        self._ewrap = tk.Frame(row, bg=C["ctrl_fill"],
                               highlightbackground=C["ctrl_stroke"],
                               highlightthickness=1)
        self._ewrap.pack(side="left", fill="x", expand=True)

        self._var = tk.StringVar()
        self._entry = tk.Entry(self._ewrap, textvariable=self._var,
            font=FONT_MONO_LG, bg=C["ctrl_fill"], fg=C["text_caption"],
            insertbackground=C["text"], relief="flat", borderwidth=0)
        self._entry.pack(fill="x", padx=12, pady=9)
        self._entry.insert(0, self._PH)
        self._entry.bind("<FocusIn>",  self._fi)
        self._entry.bind("<FocusOut>", self._fo)
        self._entry.bind("<Return>",   lambda e: self._verify())

        self._vbtn = FlatBtn(row, text="Verificar", icon="🔍",
                              variant="accent", command=self._verify)
        self._vbtn.config(font=FONT_UI_BODY_B)
        self._vbtn.pack(side="left", padx=(8, 0))

        # Format chips
        chips = tk.Frame(ic.inner, bg=C["surface_card"])
        chips.pack(anchor="w")
        for lbl, ex in [("Código:","ABC-DEF-GHI"),("IP:","192.168.1.50"),
                        ("Hostname:","SERVIDOR01")]:
            r = tk.Frame(chips, bg=C["surface_card"])
            r.pack(side="left", padx=(0, 18))
            tk.Label(r, text=lbl, font=FONT_UI_SM, bg=C["surface_card"],
                     fg=C["text_caption"]).pack(side="left")
            tk.Label(r, text=f" {ex}", font=FONT_MONO, bg=C["surface_card"],
                     fg=C["text_secondary"]).pack(side="left")

        # Preview
        self._preview = ConnectionPreview(pad)
        self._preview.pack_forget()

        # ── Scan section ──────────────────────────────────────────────────
        scan_hdr = tk.Frame(pad, bg=C["surface"])
        scan_hdr.pack(fill="x", pady=(22, 8))

        SectionHeader(scan_hdr,
            title="Computadores na rede local",
            subtitle="Máquinas com RemoteLink detectadas automaticamente",
            bg=C["surface"]).pack(side="left", anchor="w")

        self._scan_btn = FlatBtn(scan_hdr, text="Escanear rede", icon="⟳",
                                  variant="default", command=self._scan)
        self._scan_btn.pack(side="right", anchor="center")

        self._prog = ttk.Progressbar(pad, mode="determinate",
                                      style="Horizontal.TProgressbar")

        # Table
        tc = CardFrame(pad, padding=0)
        tc.pack(fill="both", expand=True)

        cols = ("host","ip","method","status")
        self._tree = ttk.Treeview(tc.inner, columns=cols, show="headings",
                                   height=6, selectmode="browse")
        for col, head, w in [("host","Hostname",210),("ip","IP",140),
                              ("method","Método",130),("status","Status",90)]:
            self._tree.heading(col, text=head)
            self._tree.column(col, width=w, minwidth=70)
        vsb2 = ttk.Scrollbar(tc.inner, orient="vertical",
                              command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb2.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._tree_dbl)
        self._tree.insert("","end",
            values=("Clique em 'Escanear rede' para buscar computadores","","",""))

    def _fi(self, e):
        if self._entry.get() == self._PH:
            self._entry.delete(0, "end")
            self._entry.config(fg=C["text"])
        self._ewrap.config(highlightbackground=C["border_focus"])

    def _fo(self, e):
        if not self._entry.get():
            self._entry.insert(0, self._PH)
            self._entry.config(fg=C["text_caption"])
        self._ewrap.config(highlightbackground=C["ctrl_stroke"])

    def _verify(self):
        t = self._var.get().strip()
        if not t or t == self._PH:
            return
        resolved = resolve_target(t)
        if not resolved:
            messagebox.showerror("Erro", "Formato inválido.")
            return
        self._preview.show_loading(t)
        self._preview.pack(fill="x", pady=(0, 8))

        def probe():
            if resolved.get("ip"):
                info = probe_target(resolved["ip"])
                info.update({"method": resolved["method"],
                             "hostname": resolved.get("hostname") or info.get("hostname")})
            else:
                info = {"reachable": False, "ip": None,
                        "hostname": resolved.get("hostname"),
                        "method": resolved["method"]}
            if resolved["method"] == "access_code":
                info.update({"method": "access_code", "code": resolved["code"]})
            self.after(0, lambda: self._preview.show_result(
                info, connect_callback=self._on_connect))

        threading.Thread(target=probe, daemon=True).start()

    def _scan(self):
        self._scan_btn.config(state="disabled", text="  Escaneando…")
        self._prog.pack(fill="x", pady=(0, 6))
        self._prog["value"] = 0
        for i in self._tree.get_children():
            self._tree.delete(i)

        def run():
            found = scan_local_network(
                lambda p: self.after(0, lambda: self._prog.config(value=p*100)))
            self.after(0, lambda: self._scan_done(found))

        threading.Thread(target=run, daemon=True).start()

    def _scan_done(self, found):
        self._scan_btn.config(state="normal", text="⟳  Escanear rede")
        self._prog.pack_forget()
        for m in found:
            self._tree.insert("","end",
                values=(m.get("hostname","—"), m.get("ip","—"),
                        "Rede Local", "Online"),
                tags=(m.get("ip",""),))
        if not found:
            self._tree.insert("","end",
                values=("Nenhum computador RemoteLink encontrado","","",""))

    def _tree_dbl(self, e):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0], "values")
        if vals and vals[1]:
            self._entry.delete(0,"end")
            self._entry.insert(0, vals[1])
            self._entry.config(fg=C["text"])
            self._verify()


# ── Share Page ─────────────────────────────────────────────────────────────────

class SharePage(tk.Frame):
    def __init__(self, parent, machine_info: dict, server: RemoteLinkServer, **kw):
        kw.setdefault("bg", C["surface"])
        super().__init__(parent, **kw)
        self.machine_info = machine_info
        self.server = server
        self._running = False
        self._build()

    def _build(self):
        pad = tk.Frame(self, bg=C["surface"])
        pad.pack(fill="both", expand=True, padx=32, pady=28)

        SectionHeader(pad,
            title="Compartilhar esta tela",
            subtitle="Permita que outro computador se conecte e controle esta máquina remotamente",
        ).pack(anchor="w", pady=(0, 20))

        # Control card
        cc = CardFrame(pad, padding=20)
        cc.pack(fill="x", pady=(0, 16))

        self._srv_dot = StatusDot(cc.inner, bg=C["surface_card"])
        self._srv_dot.pack(anchor="w", pady=(0, 14))
        self._srv_dot.set("stopped")

        self._toggle = FlatBtn(cc.inner, text="Iniciar servidor", icon="▶",
                                variant="success", command=self._do_toggle)
        self._toggle.config(font=FONT_UI_BODY_B)
        self._toggle.pack(anchor="w", pady=(0, 14))

        Divider(cc.inner).pack(fill="x", pady=(0, 10))

        tk.Label(cc.inner,
            text="⚠  Ao iniciar, qualquer pessoa com seu código de acesso pode visualizar\n"
                 "    e controlar esta tela. Pare o servidor quando não estiver em uso.",
            font=FONT_UI_SM, bg=C["surface_card"], fg=C["text_secondary"],
            justify="left", wraplength=480).pack(anchor="w")

        # Log
        SectionHeader(pad, title="Registro de conexões",
                      bg=C["surface"]).pack(anchor="w", pady=(20, 8))

        lc = CardFrame(pad, padding=0)
        lc.pack(fill="both", expand=True)

        self._log = tk.Text(lc.inner, height=9,
            bg=C["code_bg"], fg=C["text"], font=FONT_MONO,
            relief="flat", borderwidth=0, padx=14, pady=10,
            state="disabled", cursor="arrow")
        lvsb = ttk.Scrollbar(lc.inner, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=lvsb.set)
        self._log.pack(side="left", fill="both", expand=True)
        lvsb.pack(side="right", fill="y")
        self._write("Sistema pronto. Use o botão acima para iniciar o servidor.")

    def _do_toggle(self):
        if not self._running:
            self.server.start()
            self._running = True
            self._toggle.config(text="⏹  Parar servidor",
                                bg=C["error"], activebackground=C["error_hover"])
            self._srv_dot.set("listening", "Aguardando conexões na porta 52340")
            self._write("▶  Servidor iniciado — porta 52340")
        else:
            self.server.stop()
            self._running = False
            self._toggle.config(text="▶  Iniciar servidor",
                                bg=C["success"], activebackground="#0A6A0A")
            self._srv_dot.set("stopped")
            self._write("⏹  Servidor parado")

    def on_client_connected(self, addr, info):
        h = info.get("hostname", str(addr))
        self.after(0, lambda: (
            self._srv_dot.set("connected", f"Conectado: {h}"),
            self._write(f"✓  Cliente conectado — {h}  ({addr[0]})")
        ))

    def on_client_disconnected(self):
        self.after(0, lambda: (
            self._srv_dot.set("listening", "Aguardando conexões na porta 52340"),
            self._write("✗  Cliente desconectado")
        ))

    def _write(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.config(state="normal")
        self._log.insert("end", f"[{ts}]  {msg}\n")
        self._log.see("end")
        self._log.config(state="disabled")


# ── Machine Banner ─────────────────────────────────────────────────────────────

class MachineBanner(tk.Frame):
    """Top banner showing this machine's identity — like Windows 11 About page."""
    def __init__(self, parent, machine_info: dict, **kw):
        super().__init__(parent, bg=C["surface_card"],
                         highlightbackground=C["border"],
                         highlightthickness=1, **kw)
        self._info = machine_info
        self._build()

    def _build(self):
        inner = tk.Frame(self, bg=C["surface_card"])
        inner.pack(fill="x", padx=24, pady=16)

        # Left block: icon + names
        left = tk.Frame(inner, bg=C["surface_card"])
        left.pack(side="left", fill="y")

        tk.Label(left, text="🖥", font=_f(_UI_FAMS, 30),
                 bg=C["surface_card"]).pack(anchor="w")
        tk.Label(left, text=self._info.get("hostname", "Este Computador"),
                 font=FONT_UI_SUBH, bg=C["surface_card"],
                 fg=C["text"]).pack(anchor="w", pady=(4, 0))
        tk.Label(left,
                 text=f"{self._info.get('platform','')}  ·  IP: {self._info.get('local_ip','')}",
                 font=FONT_UI_SM, bg=C["surface_card"],
                 fg=C["text_secondary"]).pack(anchor="w", pady=(2, 0))

        # Vertical rule
        Divider(inner, vertical=True).pack(side="left", fill="y", padx=24, pady=4)

        # Right block: access code
        right = tk.Frame(inner, bg=C["surface_card"])
        right.pack(side="left", fill="y", expand=True)

        tk.Label(right, text="Seu código de acesso",
                 font=FONT_UI_SM, bg=C["surface_card"],
                 fg=C["text_caption"]).pack(anchor="w")

        code_row = tk.Frame(right, bg=C["surface_card"])
        code_row.pack(anchor="w", pady=(4, 0))

        self._code = tk.Label(code_row,
            text=self._info.get("access_code", "---"),
            font=FONT_CODE_XL, bg=C["surface_card"],
            fg=C["accent_text"], cursor="hand2")
        self._code.pack(side="left")
        self._code.bind("<Button-1>", self._copy)

        FlatBtn(code_row, text="Copiar", icon="📋",
                variant="subtle", command=self._copy).pack(
            side="left", padx=(10, 0), pady=(6, 0))

        # Status
        self._status = StatusDot(right, bg=C["surface_card"])
        self._status.pack(anchor="w", pady=(8, 0))
        self._status.set("stopped")

    def _copy(self, e=None):
        code = self._info.get("access_code", "")
        self.winfo_toplevel().clipboard_clear()
        self.winfo_toplevel().clipboard_append(code)
        orig = self._code.cget("text")
        self._code.config(text="✓  Copiado!", fg=C["success"])
        self.after(1800, lambda: self._code.config(text=orig, fg=C["accent_text"]))

    def update_status(self, status: str):
        labels = {"listening":"Aguardando conexões","connected":"Cliente conectado",
                  "stopped":"Servidor parado","error":"Erro no servidor"}
        self._status.set(status, labels.get(status, status))


# ── Viewer Window ──────────────────────────────────────────────────────────────

class ViewerWindow(tk.Toplevel):
    def __init__(self, parent, client: RemoteLinkClient, remote_info: dict):
        super().__init__(parent)
        self.client = client
        self.remote_info = remote_info
        hostname = remote_info.get("hostname", "Remoto")
        self.title(f"RemoteLink  —  {hostname}")
        self.configure(bg="#000000")
        self.geometry("1152x720")
        self.minsize(640, 480)
        self._rw = 1920
        self._rh = 1080
        self._enabled = True
        self._fc = 0
        self._fts = time.time()
        self._photo = None
        self._cimg = None
        self._build()
        self.client.on_frame = self._on_frame
        self.client.on_disconnected = self._disconnected
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self):
        tb = tk.Frame(self, bg=C["surface"], height=44)
        tb.pack(fill="x")
        tb.pack_propagate(False)

        h = self.remote_info.get("hostname","—")
        ip = self.remote_info.get("ip","")
        tk.Label(tb, text="RemoteLink", font=FONT_UI_SM,
                 bg=C["surface"], fg=C["text_secondary"]).pack(side="left", padx=(14,0))
        tk.Label(tb, text=" › ", font=FONT_UI_SM,
                 bg=C["surface"], fg=C["text_disabled"]).pack(side="left")
        tk.Label(tb, text=h, font=FONT_UI_BODY_B,
                 bg=C["surface"], fg=C["text"]).pack(side="left")
        if ip:
            tk.Label(tb, text=f"  ({ip})", font=FONT_UI_SM,
                     bg=C["surface"], fg=C["text_secondary"]).pack(side="left")

        self._fps = tk.Label(tb, text="— fps", font=FONT_MONO,
                              bg=C["surface"], fg=C["text_caption"])
        self._fps.pack(side="right", padx=(0, 10))
        self._cstatus = tk.Label(tb, text="● Conectado", font=FONT_UI_SM,
                                  bg=C["surface"], fg=C["success"])
        self._cstatus.pack(side="right", padx=(0, 10))

        FlatBtn(tb, text="Desconectar", icon="⊗", variant="danger",
                command=self._close).pack(side="right", padx=(0,8), pady=6)

        for lbl, fn in [
            ("Ctrl+Alt+Del", lambda: self.client.send_hotkey("ctrl","alt","delete")),
            ("Win",          lambda: self.client.send_key_press("win")),
            ("Alt+Tab",      lambda: self.client.send_hotkey("alt","tab")),
        ]:
            FlatBtn(tb, text=lbl, variant="subtle",
                    command=fn).pack(side="left", padx=2, pady=6)

        Divider(self).pack(fill="x")

        self._cv = tk.Canvas(self, bg="#000000", cursor="none",
                              highlightthickness=0)
        self._cv.pack(fill="both", expand=True)

        self._cv.bind("<Motion>",          self._mv)
        self._cv.bind("<Button-1>",        lambda e: self._cl(e,"left"))
        self._cv.bind("<Button-3>",        lambda e: self._cl(e,"right"))
        self._cv.bind("<Button-2>",        lambda e: self._cl(e,"middle"))
        self._cv.bind("<Double-Button-1>", self._db)
        self._cv.bind("<MouseWheel>",      self._sc)
        self.bind("<KeyPress>",            self._kp)
        self.focus_set()
        self._upd_fps()

    def _on_frame(self, data, ts):
        try:
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(data))
            self._rw, self._rh = img.size
            cw = self._cv.winfo_width()
            ch = self._cv.winfo_height()
            if cw > 1 and ch > 1:
                img.thumbnail((cw, ch), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            def upd():
                self._photo = photo
                if self._cimg is None:
                    self._cimg = self._cv.create_image(
                        cw//2, ch//2, image=photo, anchor="center")
                else:
                    self._cv.coords(self._cimg, cw//2, ch//2)
                    self._cv.itemconfig(self._cimg, image=photo)
            self.after(0, upd)
            self._fc += 1
        except Exception:
            pass

    def _tr(self, cx, cy):
        cw = self._cv.winfo_width()
        ch = self._cv.winfo_height()
        if cw <= 0 or ch <= 0:
            return cx, cy
        sc = min(cw/self._rw, ch/self._rh)
        ox = (cw - int(self._rw*sc))//2
        oy = (ch - int(self._rh*sc))//2
        return (max(0, min(int((cx-ox)/sc), self._rw)),
                max(0, min(int((cy-oy)/sc), self._rh)))

    def _mv(self, e):
        if self._enabled:
            rx,ry = self._tr(e.x,e.y); self.client.send_mouse_move(rx,ry)
    def _cl(self, e, btn):
        if self._enabled:
            rx,ry = self._tr(e.x,e.y); self.client.send_mouse_click(rx,ry,btn)
    def _db(self, e):
        if self._enabled:
            rx,ry = self._tr(e.x,e.y); self.client.send_mouse_dblclick(rx,ry)
    def _sc(self, e):
        if self._enabled:
            rx,ry = self._tr(e.x,e.y)
            self.client.send_mouse_scroll(rx,ry, 1 if e.delta>0 else -1)
    def _kp(self, e):
        if not self._enabled: return
        km = {"Return":"enter","BackSpace":"backspace","Delete":"delete",
              "Escape":"escape","Tab":"tab","space":"space",
              "Up":"up","Down":"down","Left":"left","Right":"right",
              "Home":"home","End":"end","Prior":"pageup","Next":"pagedown",
              **{f"F{i}":f"f{i}" for i in range(1,13)}}
        if e.keysym in km:
            self.client.send_key_press(km[e.keysym])
        elif e.char and len(e.char)==1:
            self.client.send_text(e.char)

    def _disconnected(self):
        self.after(0, lambda: self._cstatus.config(
            text="● Desconectado", fg=C["error"]))

    def _upd_fps(self):
        el = time.time()-self._fts
        if el >= 1.0:
            try:
                self._fps.config(text=f"{self._fc/el:.0f} fps")
            except Exception: return
            self._fc = 0; self._fts = time.time()
        self.after(1000, self._upd_fps)

    def _close(self):
        self._enabled = False
        self.client.disconnect()
        self.destroy()


# ── Main App ───────────────────────────────────────────────────────────────────

class RemoteLinkApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RemoteLink")
        self.geometry("980x680")
        self.minsize(800, 560)
        self.configure(bg=C["surface"])
        configure_styles()

        self.machine_info = get_machine_info()
        self.server = RemoteLinkServer(access_code=self.machine_info["access_code"])
        self.client: Optional[RemoteLinkClient] = None
        self.viewer_window: Optional[ViewerWindow] = None

        self._build()
        self.after(400, self._autostart)

    def _build(self):
        # Top banner
        self._banner = MachineBanner(self, self.machine_info)
        self._banner.pack(fill="x")
        Divider(self).pack(fill="x")

        # Body
        body = tk.Frame(self, bg=C["surface"])
        body.pack(fill="both", expand=True)

        # Nav sidebar
        nav = tk.Frame(body, bg=C["nav_bg"], width=196)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Frame(nav, height=10, bg=C["nav_bg"]).pack()

        # Content
        self._content = tk.Frame(body, bg=C["surface"])
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

        self.server.on_client_connect    = _on_connect
        self.server.on_client_disconnect = _on_disconnect
        self.server.on_status_change     = _on_status

        # Nav items
        self._navitems = {}
        for key, icon, label in [
            ("connect", "→",  "Conectar"),
            ("share",   "⇅", "Compartilhar"),
        ]:
            ni = NavItem(nav, icon, label,
                         command=lambda k=key: self._show(k))
            ni.pack(fill="x", padx=8, pady=2)
            self._navitems[key] = ni

        # Footer
        tk.Frame(nav, bg=C["nav_bg"]).pack(fill="y", expand=True)
        Divider(nav).pack(fill="x", padx=8)
        tk.Label(nav, text="RemoteLink  v1.0",
                 font=FONT_UI_SM, bg=C["nav_bg"],
                 fg=C["text_caption"]).pack(pady=10)

        self._show("connect")

    def _show(self, key):
        for p in self._pages.values():
            p.pack_forget()
        for k, ni in self._navitems.items():
            ni.activate(k == key)
        self._pages[key].pack(fill="both", expand=True)

    def _autostart(self):
        self._pages["share"]._do_toggle()

    def _do_connect(self, info: dict):
        ip = info.get("ip")
        if not ip:
            messagebox.showerror("Erro",
                "Não foi possível resolver o endereço.\n"
                "Verifique o código ou hostname e tente novamente.")
            return
        self.client = RemoteLinkClient(
            on_status_change=lambda s: None,
            on_error=lambda e: self.after(0, lambda: messagebox.showerror("Erro", e)),
        )
        def run():
            code = info.get("code","") or self.machine_info["access_code"]
            ok = self.client.connect(ip=ip, access_code=code,
                                      local_access_code=self.machine_info["access_code"])
            if ok:
                rinfo = self.client.remote_info or {}
                rinfo["ip"] = ip
                self.after(0, lambda: self._open_viewer(rinfo))
            else:
                self.client = None
        threading.Thread(target=run, daemon=True).start()

    def _open_viewer(self, remote_info):
        if self.viewer_window and self.viewer_window.winfo_exists():
            self.viewer_window.lift(); return
        self.viewer_window = ViewerWindow(self, self.client, remote_info)
        self.viewer_window.focus()


def main():
    app = RemoteLinkApp()
    app.mainloop()


if __name__ == "__main__":
    main()
