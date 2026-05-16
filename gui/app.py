"""
RemoteLink - GUI Application
Dark theme - profissional e moderna
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

from core.identity import get_machine_info, resolve_target, NetworkScanner, is_local_target, is_own_code
from core.client import RemoteLinkClient, probe_target, probe_hostname, resolve_hostname_to_ips
from core.server import RemoteLinkServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remotelink.gui")

# ── Dark Theme ─────────────────────────────────────────────────────────────────
C = {
    "bg_dark":       "#0d1117",
    "bg_surface":    "#161b22",
    "bg_card":       "#1c2333",
    "bg_alt":        "#21262d",
    "bg_input":      "#0d1117",
    "border":        "#30363d",
    "border_focus":  "#58a6ff",
    "accent":        "#58a6ff",
    "accent_hover":  "#79c0ff",
    "accent_muted":  "#1f3a5f",
    "success":       "#3fb950",
    "success_bg":    "#1b3624",
    "warning":       "#d29922",
    "warning_bg":    "#2d2416",
    "error":         "#f85149",
    "error_bg":      "#2d1b1b",
    "error_hover":   "#da3a33",
    "text":          "#e6edf3",
    "text_secondary":"#8b949e",
    "text_disabled": "#484f58",
    "text_caption":  "#6e7681",
    "text_on_accent":"#ffffff",
    "nav_bg":        "#111820",
    "nav_hover":     "#1c2333",
    "nav_active":    "#161b22",
    "nav_active_bar":"#58a6ff",
    "ctrl_hover":    "#292e36",
    "scroll_bg":     "#161b22",
    "scroll_fg":     "#30363d",
    "scroll_hover":  "#484f58",
    "code_bg":       "#161b22",
    "code_text":     "#79c0ff",
    "progress_bg":   "#21262d",
    "progress_fg":   "#58a6ff",
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
        background=[("active", "#2ea043")])

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
                     wraplength=500, justify="left").pack(anchor="w", pady=(2, 0))


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
                        abg="#2ea043", afg=C["text_on_accent"],
                        hl="", hlt=0, px=14, py=6),
        "subtle":  dict(bg=C["bg_surface"], fg=C["text_secondary"],
                        abg=C["bg_alt"], afg=C["text"],
                        hl="", hlt=0, px=10, py=5),
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
            "listening": "Aguardando conexoes", "connecting": "Conectando...",
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
        self._spin_txt = tk.Label(self._load_f, text="Verificando na rede...",
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

        methods = {"ip":"IP Direto","hostname":"Hostname / DNS",
                   "access_code":"Codigo de Acesso","scan":"Descoberta Local"}

        self._host_lbl.config(text=hostname)
        self._plat_lbl.config(text=plat or "Sistema Remoto")
        self._dvals["ip"].config(text=info.get("ip") or info.get("local_ip") or "\u2014")
        self._dvals["hostname"].config(text=hostname)
        self._dvals["platform"].config(text=plat or "\u2014")
        self._dvals["method"].config(
            text=methods.get(info.get("method",""), info.get("method","\u2014")))

        for w in self._badge_f.winfo_children():
            w.destroy()

        if reachable:
            self._title.config(text="Maquina encontrada - pronta para conectar")
            Badge(self._badge_f, "Online", "success").pack()
            self._conn_btn.config(bg=C["accent"], state="normal",
                                  text="Conectar")
        else:
            self._title.config(text="Maquina nao alcancavel")
            Badge(self._badge_f, "Offline", "error").pack()
            self._conn_btn.config(bg=C["text_disabled"], state="disabled",
                                  text="Inacessivel")

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


# ── Connect Page ───────────────────────────────────────────────────────────────

class ConnectPage(tk.Frame):
    _PH = "Codigo, IP ou Hostname - ex: 123-456"

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
        pad.pack(fill="both", expand=True, padx=32, pady=28)

        SectionHeader(pad,
            title="Conectar a um computador remoto",
            subtitle="Digite o codigo de acesso, hostname ou IP do computador que deseja controlar",
        ).pack(anchor="w", pady=(0, 20))

        # ── Input card ────────────────────────────────────────────────────
        ic = CardFrame(pad, padding=20)
        ic.pack(fill="x", pady=(0, 4))

        tk.Label(ic.inner, text="Endereco do computador",
                 font=FONT_UI_BODY_B, bg=C["bg_card"],
                 fg=C["text"]).pack(anchor="w", pady=(0, 8))

        row = tk.Frame(ic.inner, bg=C["bg_card"])
        row.pack(fill="x", pady=(0, 10))

        self._ewrap = tk.Frame(row, bg=C["bg_input"],
                               highlightbackground=C["border"],
                               highlightthickness=1)
        self._ewrap.pack(side="left", fill="x", expand=True)

        self._var = tk.StringVar()
        self._entry = tk.Entry(self._ewrap, textvariable=self._var,
            font=FONT_MONO_LG, bg=C["bg_input"], fg=C["text_caption"],
            insertbackground=C["text"], relief="flat", borderwidth=0)
        self._entry.pack(fill="x", padx=12, pady=9)
        self._entry.insert(0, self._PH)
        self._entry.bind("<FocusIn>",  self._fi)
        self._entry.bind("<FocusOut>", self._fo)
        self._entry.bind("<Return>",   lambda e: self._verify())

        self._vbtn = FlatBtn(row, text="Verificar",
                              variant="accent", command=self._verify)
        self._vbtn.config(font=FONT_UI_BODY_B)
        self._vbtn.pack(side="left", padx=(8, 0))

        # Format chips
        chips = tk.Frame(ic.inner, bg=C["bg_card"])
        chips.pack(anchor="w")
        for lbl, ex in [("Codigo:","123-456"),("IP:","192.168.1.50"),
                        ("Hostname:","SERVIDOR01")]:
            r = tk.Frame(chips, bg=C["bg_card"])
            r.pack(side="left", padx=(0, 18))
            tk.Label(r, text=lbl, font=FONT_UI_SM, bg=C["bg_card"],
                     fg=C["text_caption"]).pack(side="left")
            tk.Label(r, text=f" {ex}", font=FONT_MONO, bg=C["bg_card"],
                     fg=C["text_secondary"]).pack(side="left")

        # Preview
        self._preview = ConnectionPreview(pad)
        self._preview.pack_forget()

        # ── Scan section ──────────────────────────────────────────────────
        scan_hdr = tk.Frame(pad, bg=C["bg_surface"])
        scan_hdr.pack(fill="x", pady=(22, 8))

        SectionHeader(scan_hdr,
            title="Computadores na rede local",
            subtitle="Maquinas com RemoteLink detectadas automaticamente",
            bg=C["bg_surface"]).pack(side="left", anchor="w")

        self._scan_btn = FlatBtn(scan_hdr, text="Escanearede",
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
                              ("method","Metodo",130),("status","Status",90)]:
            self._tree.heading(col, text=head)
            self._tree.column(col, width=w, minwidth=70)
        vsb2 = ttk.Scrollbar(tc.inner, orient="vertical",
                              command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb2.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._tree_dbl)
        self._tree.insert("","end",
            values=("Clique em 'Escanearede' para buscar computadores","","",""))

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

    def _verify(self):
        t = self._var.get().strip()
        if not t or t == self._PH:
            return
        resolved = resolve_target(t)
        if not resolved:
            messagebox.showerror("Erro", "Formato invalido. Use codigo XXX-XXX, IP ou hostname.")
            return
        # Impede conexao com a propria maquina
        if resolved["method"] == "access_code":
            if is_own_code(resolved.get("code", "")):
                messagebox.showerror("Restricao", "Voce nao pode se conectar ao seu proprio codigo de acesso.")
                self._preview.pack_forget()
                return
        elif resolved["method"] in ("ip", "hostname"):
            target_check = resolved.get("ip") or resolved.get("hostname") or t
            if is_local_target(target_check):
                messagebox.showerror("Restricao", "Nao e possivel conectar a si mesmo.\n\nUse o codigo ou IP de outro computador.")
                self._preview.pack_forget()
                return

        self._preview.show_loading(t)
        self._preview.pack(fill="x", pady=(0, 8))

        def probe():
            method = resolved["method"]
            if method == "access_code":
                info = {"reachable": False, "ip": None,
                        "method": "access_code",
                        "code": resolved["code"],
                        "hostname": "Aguardando descoberta local...",
                        "platform": ""}
                info["reachable"] = True
                info["status"] = "pending_scan"
            elif method == "hostname" and not resolved.get("ip"):
                info = probe_hostname(resolved["hostname"])
                info["method"] = "hostname"
                if not info.get("ip"):
                    info["reachable"] = False
                    info["error"] = "Hostname nao encontrado na rede"
            elif method == "hostname" and resolved.get("ip"):
                info = probe_target(resolved["ip"])
                info["method"] = "hostname"
                info["hostname"] = resolved.get("hostname") or info.get("hostname")
            else:
                info = probe_target(resolved["ip"])
                info["method"] = "ip"
                info["hostname"] = resolved.get("hostname") or info.get("hostname") or resolved["ip"]

            self.after(0, lambda: self._preview.show_result(
                info, connect_callback=self._on_connect))

        threading.Thread(target=probe, daemon=True, name="RL-Probe").start()

    _active_scanner = None

    def _scan(self):
        if self._active_scanner:
            self._active_scanner.stop()

        self._scan_btn.config(state="disabled", text="Escaneando...")
        self._prog.pack(fill="x", pady=(0, 6))
        self._prog["value"] = 0
        for i in self._tree.get_children():
            self._tree.delete(i)

        def on_found(machine):
            self.after(0, lambda m=machine: self._tree.insert(
                "", "end",
                values=(m.get("hostname","\u2014"), m.get("ip","\u2014"),
                        "Rede Local", "Online"),
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
        self._scan_btn.config(state="normal", text="Escanearede")
        self._prog.pack_forget()
        if not found and not self._tree.get_children():
            self._tree.insert("", "end",
                values=("Nenhum computador RemoteLink encontrado na rede","","",""))

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
        kw.setdefault("bg", C["bg_surface"])
        super().__init__(parent, **kw)
        self.machine_info = machine_info
        self.server = server
        self._running = False
        self._build()

    def _build(self):
        pad = tk.Frame(self, bg=C["bg_surface"])
        pad.pack(fill="both", expand=True, padx=32, pady=28)

        SectionHeader(pad,
            title="Compartilhar esta tela",
            subtitle="Permita que outro computador se conecte e controle esta maquina remotamente",
        ).pack(anchor="w", pady=(0, 20))

        # Control card
        cc = CardFrame(pad, padding=20)
        cc.pack(fill="x", pady=(0, 16))

        self._srv_dot = StatusDot(cc.inner, bg=C["bg_card"])
        self._srv_dot.pack(anchor="w", pady=(0, 14))
        self._srv_dot.set("stopped")

        self._toggle = FlatBtn(cc.inner, text="Iniciar servidor",
                                variant="success", command=self._do_toggle)
        self._toggle.config(font=FONT_UI_BODY_B)
        self._toggle.pack(anchor="w", pady=(0, 14))

        Divider(cc.inner).pack(fill="x", pady=(0, 10))

        tk.Label(cc.inner,
            text="Ao iniciar, qualquer pessoa com seu codigo de acesso pode visualizar\n"
                 "e controlar esta tela. Pare o servidor quando nao estiver em uso.",
            font=FONT_UI_SM, bg=C["bg_card"], fg=C["text_secondary"],
            justify="left", wraplength=480).pack(anchor="w")

        # Log
        SectionHeader(pad, title="Registro de conexoes",
                      bg=C["bg_surface"]).pack(anchor="w", pady=(20, 8))

        lc = CardFrame(pad, padding=0)
        lc.pack(fill="both", expand=True)

        self._log = tk.Text(lc.inner, height=9,
            bg=C["bg_dark"], fg=C["text"], font=FONT_MONO,
            relief="flat", borderwidth=0, padx=14, pady=10,
            state="disabled", cursor="arrow")
        lvsb = ttk.Scrollbar(lc.inner, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=lvsb.set)
        self._log.pack(side="left", fill="both", expand=True)
        lvsb.pack(side="right", fill="y")
        self._write("Sistema pronto. Use o botao acima para iniciar o servidor.")

    def _do_toggle(self):
        if not self._running:
            self.server.start()
            self._running = True
            self._toggle.config(text="Parar servidor",
                                bg=C["error"], activebackground=C["error_hover"])
            self._srv_dot.set("listening", "Aguardando conexoes na porta 52340")
            self._write("Servidor iniciado - porta 52340")
        else:
            self.server.stop()
            self._running = False
            self._toggle.config(text="Iniciar servidor",
                                bg=C["success"], activebackground="#2ea043")
            self._srv_dot.set("stopped")
            self._write("Servidor parado")

    def on_client_connected(self, addr, info):
        h = info.get("hostname", str(addr))
        self.after(0, lambda: (
            self._srv_dot.set("connected", f"Conectado: {h}"),
            self._write(f"Cliente conectado - {h} ({addr[0]})")
        ))

    def on_client_disconnected(self):
        self.after(0, lambda: (
            self._srv_dot.set("listening", "Aguardando conexoes na porta 52340"),
            self._write("Cliente desconectado")
        ))

    def _write(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log.config(state="normal")
        self._log.insert("end", f"[{ts}] {msg}\n")
        self._log.see("end")
        self._log.config(state="disabled")


# ── Machine Banner ─────────────────────────────────────────────────────────────

class MachineBanner(tk.Frame):
    def __init__(self, parent, machine_info: dict, **kw):
        super().__init__(parent, bg=C["bg_card"],
                         highlightbackground=C["border"],
                         highlightthickness=1, **kw)
        self._info = machine_info
        self._build()

    def _build(self):
        inner = tk.Frame(self, bg=C["bg_card"])
        inner.pack(fill="x", padx=24, pady=14)

        # Left: hostname + IP
        left = tk.Frame(inner, bg=C["bg_card"])
        left.pack(side="left", fill="y")

        tk.Label(left, text=self._info.get("hostname", "Este Computador"),
                 font=FONT_UI_SUBH, bg=C["bg_card"],
                 fg=C["text"]).pack(anchor="w")
        ips_text = " | ".join(self._info.get("all_ips", []))
        tk.Label(left,
                 text=f"{self._info.get('platform','')}  |  {ips_text}",
                 font=FONT_UI_SM, bg=C["bg_card"],
                 fg=C["text_secondary"]).pack(anchor="w", pady=(2, 0))

        Divider(inner, vertical=True).pack(side="left", fill="y", padx=24, pady=4)

        # Right: access code
        right = tk.Frame(inner, bg=C["bg_card"])
        right.pack(side="left", fill="y", expand=True)

        tk.Label(right, text="Seu codigo de acesso",
                 font=FONT_UI_SM, bg=C["bg_card"],
                 fg=C["text_caption"]).pack(anchor="w")

        code_row = tk.Frame(right, bg=C["bg_card"])
        code_row.pack(anchor="w", pady=(4, 0))

        self._code = tk.Label(code_row,
            text=self._info.get("access_code", "---"),
            font=FONT_CODE_XL, bg=C["bg_card"],
            fg=C["accent"], cursor="hand2")
        self._code.pack(side="left")
        self._code.bind("<Button-1>", self._copy)

        FlatBtn(code_row, text="Copiar",
                variant="subtle", command=self._copy).pack(
            side="left", padx=(10, 0), pady=(6, 0))

        # Status
        self._status = StatusDot(right, bg=C["bg_card"])
        self._status.pack(anchor="w", pady=(8, 0))
        self._status.set("stopped")

    def _copy(self, e=None):
        code = self._info.get("access_code", "")
        self.winfo_toplevel().clipboard_clear()
        self.winfo_toplevel().clipboard_append(code)
        orig = self._code.cget("text")
        self._code.config(text="Copiado!", fg=C["success"])
        self.after(1800, lambda: self._code.config(text=orig, fg=C["accent"]))

    def update_status(self, status: str):
        labels = {"listening":"Aguardando conexoes","connected":"Cliente conectado",
                  "stopped":"Servidor parado","error":"Erro no servidor"}
        self._status.set(status, labels.get(status, status))


# ── Viewer Window ──────────────────────────────────────────────────────────────

class ViewerWindow(tk.Toplevel):
    def __init__(self, parent, client: RemoteLinkClient, remote_info: dict):
        super().__init__(parent)
        self.client      = client
        self.remote_info = remote_info

        hostname = remote_info.get("hostname", remote_info.get("ip", "Remoto"))
        self.title(f"RemoteLink - {hostname}")
        self.configure(bg="#0d1117")
        self.geometry("1280x760")
        self.minsize(800, 500)

        self._rw = 1920
        self._rh = 1080

        self._photo        = None
        self._cimg         = None
        self._latest_frame = None
        self._frame_lock   = threading.Lock()
        self._fc           = 0
        self._fts          = time.time()
        self._enabled      = True

        self._capturing = False

        self._build()

        self.client.on_frame        = self._on_frame
        self.client.on_disconnected = self._on_disconnected
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._schedule_render()
        self._update_fps()

    def _build(self):
        h  = self.remote_info.get("hostname", self.remote_info.get("ip", "\u2014"))
        ip = self.remote_info.get("ip", "")

        # ── Toolbar ───────────────────────────────────────────────────────
        tb = tk.Frame(self, bg=C["bg_dark"], height=42)
        tb.pack(fill="x", side="top")
        tb.pack_propagate(False)

        tk.Label(tb, text="RemoteLink", font=FONT_UI_SM,
                 bg=C["bg_dark"], fg=C["text_secondary"]).pack(side="left", padx=(14,0))
        tk.Label(tb, text=">", font=FONT_UI_SM,
                 bg=C["bg_dark"], fg=C["text_disabled"]).pack(side="left", padx=(4,4))
        tk.Label(tb, text=f" {h}", font=FONT_UI_BODY_B,
                 bg=C["bg_dark"], fg=C["text"]).pack(side="left")
        if ip and ip != h:
            tk.Label(tb, text=f" ({ip})", font=FONT_UI_SM,
                     bg=C["bg_dark"], fg=C["text_secondary"]).pack(side="left")

        tk.Frame(tb, width=14, bg=C["bg_dark"]).pack(side="left")

        def btn(lbl, cmd):
            FlatBtn(tb, text=lbl, variant="subtle",
                    command=cmd).pack(side="left", padx=2, pady=6)

        btn("Alt+Tab",      self._send_alt_tab)
        btn("Win",          self._send_win)
        btn("Ctrl+Alt+Del", self._send_cad)
        btn("PrtScr",       self._send_prtscr)
        btn("Ctrl+C",       lambda: self.client.send_hotkey("ctrl","c"))
        btn("Ctrl+V",       lambda: self.client.send_hotkey("ctrl","v"))
        btn("Ctrl+Z",       lambda: self.client.send_hotkey("ctrl","z"))
        btn("Ctrl+W",       lambda: self.client.send_hotkey("ctrl","w"))

        FlatBtn(tb, text="Desconectar", variant="danger",
                command=self._close).pack(side="right", padx=(0,10), pady=6)

        self._cstatus = tk.Label(tb, text="Conectado", font=FONT_UI_SM,
                                  bg=C["bg_dark"], fg=C["success"])
        self._cstatus.pack(side="right", padx=(0,10))

        self._fps_lbl = tk.Label(tb, text="- fps", font=FONT_MONO,
                                  bg=C["bg_dark"], fg=C["text_caption"])
        self._fps_lbl.pack(side="right", padx=(0,6))

        self._mode_lbl = tk.Label(tb, text="Local", font=FONT_UI_SM,
                                   bg=C["bg_dark"], fg=C["text_secondary"],
                                   cursor="hand2")
        self._mode_lbl.pack(side="right", padx=(0,10))
        self._mode_lbl.bind("<Button-1>", lambda e: self._toggle_capture())

        Divider(self, color=C["bg_dark"]).pack(fill="x")

        # ── Canvas ────────────────────────────────────────────────────────
        self._cv = tk.Canvas(self, bg="#0d1117", highlightthickness=0,
                              cursor="none")
        self._cv.pack(fill="both", expand=True)

        self._cursor_item = self._cv.create_oval(
            -20, -20, -10, -10,
            fill="#f85149", outline="#ffffff", width=1.5,
            tags="cursor", state="hidden")

        self._border = self._cv.create_rectangle(
            0, 0, 0, 0,
            outline=C["accent"], width=3,
            tags="border", state="hidden")

        self._cv.bind("<Enter>",           self._on_enter_canvas)
        self._cv.bind("<Leave>",           self._on_leave_canvas)
        self._cv.bind("<Motion>",          self._on_mouse_motion)
        self._cv.bind("<ButtonPress-1>",   lambda e: self._on_btn(e,"left"))
        self._cv.bind("<ButtonPress-3>",   lambda e: self._on_btn(e,"right"))
        self._cv.bind("<ButtonPress-2>",   lambda e: self._on_btn(e,"middle"))
        self._cv.bind("<Double-Button-1>", self._on_dbl)
        self._cv.bind("<MouseWheel>",      self._on_scroll)
        self._cv.bind("<Button-4>",        lambda e: self._on_scroll_delta(e,  3))
        self._cv.bind("<Button-5>",        lambda e: self._on_scroll_delta(e, -3))
        self._cv.bind("<Configure>", self._on_canvas_resize)

        self.bind("<KeyPress>",   self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)

        try:
            self.bind_all("<Alt-Tab>", self._on_key_press)
        except Exception:
            pass

    # ── Capture mode ──────────────────────────────────────────────────────

    def _on_enter_canvas(self, e):
        self._set_capturing(True)

    def _on_leave_canvas(self, e):
        self._set_capturing(False)

    def _toggle_capture(self):
        self._set_capturing(not self._capturing)

    def _set_capturing(self, active: bool):
        if self._capturing == active:
            return
        self._capturing = active

        if active:
            self._cv.config(cursor="none")
            self._cv.itemconfig("cursor", state="normal")
            self._cv.itemconfig("border", state="normal")
            self._mode_lbl.config(
                text="REMOTO", fg=C["accent"],
                font=(FONT_UI_SM[0], FONT_UI_SM[1], "bold"))
            self.focus_force()
        else:
            self._cv.config(cursor="")
            self._cv.itemconfig("cursor", state="hidden")
            self._cv.itemconfig("border", state="hidden")
            self._mode_lbl.config(
                text="Local", fg=C["text_secondary"],
                font=FONT_UI_SM)

    def _on_canvas_resize(self, e):
        w, h = e.width, e.height
        self._cv.coords("border", 2, 2, w-2, h-2)

    # ── Frame rendering ───────────────────────────────────────────────────

    def _on_frame(self, data: bytes, ts: int):
        with self._frame_lock:
            self._latest_frame = data
            self._fc += 1

    def _schedule_render(self):
        self._render_frame()
        if self._enabled:
            self.after(16, self._schedule_render)

    def _render_frame(self):
        with self._frame_lock:
            data = self._latest_frame
            self._latest_frame = None
        if not data:
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(data))
            self._rw, self._rh = img.size

            cw = self._cv.winfo_width()
            ch = self._cv.winfo_height()
            if cw < 2 or ch < 2:
                return

            sc = min(cw / self._rw, ch / self._rh)
            nw = max(1, int(self._rw * sc))
            nh = max(1, int(self._rh * sc))
            img = img.resize((nw, nh), Image.LANCZOS)

            photo = ImageTk.PhotoImage(img)
            self._photo = photo

            cx, cy = cw // 2, ch // 2
            if self._cimg is None:
                self._cimg = self._cv.create_image(cx, cy, image=photo,
                                                    anchor="center", tags="frame")
            else:
                self._cv.itemconfig(self._cimg, image=photo)
                self._cv.coords(self._cimg, cx, cy)

            self._cv.tag_lower("frame")
            self._cv.tag_raise("cursor")
            self._cv.tag_raise("border")
        except Exception as e:
            logger.debug(f"render: {e}")

    # ── Coordinate transforms ─────────────────────────────────────────────

    def _tr(self, cx, cy):
        cw = self._cv.winfo_width()
        ch = self._cv.winfo_height()
        if cw < 2 or ch < 2 or self._rw < 1 or self._rh < 1:
            return 0, 0

        sc = min(cw / self._rw, ch / self._rh)
        ox = (cw - int(self._rw * sc)) // 2
        oy = (ch - int(self._rh * sc)) // 2

        rx = int((cx - ox) / sc)
        ry = int((cy - oy) / sc)

        return max(0, min(rx, self._rw - 1)), max(0, min(ry, self._rh - 1))

    def _move_cursor(self, cx, cy):
        r = 5
        self._cv.coords("cursor", cx-r, cy-r, cx+r, cy+r)

    # ── Mouse events ──────────────────────────────────────────────────────

    def _on_mouse_motion(self, e):
        self._move_cursor(e.x, e.y)
        if self._capturing and self._enabled:
            rx, ry = self._tr(e.x, e.y)
            self.client.send_mouse_move(rx, ry)

    def _on_btn(self, e, btn: str):
        if self._capturing and self._enabled:
            rx, ry = self._tr(e.x, e.y)
            self.client.send_mouse_click(rx, ry, btn, "down")
            self.client.send_mouse_click(rx, ry, btn, "up")
        self.focus_force()

    def _on_dbl(self, e):
        if self._capturing and self._enabled:
            rx, ry = self._tr(e.x, e.y)
            self.client.send_mouse_dblclick(rx, ry)

    def _on_scroll(self, e):
        if self._capturing and self._enabled:
            rx, ry = self._tr(e.x, e.y)
            self.client.send_mouse_scroll(rx, ry, 3 if e.delta > 0 else -3)

    def _on_scroll_delta(self, e, d):
        if self._capturing and self._enabled:
            rx, ry = self._tr(e.x, e.y)
            self.client.send_mouse_scroll(rx, ry, d)

    # ── Keyboard events ───────────────────────────────────────────────────

    _KEY_MAP = {
        "Return":"enter",    "BackSpace":"backspace", "Delete":"delete",
        "Escape":"escape",   "Tab":"tab",             "space":"space",
        "Up":"up",           "Down":"down",           "Left":"left",
        "Right":"right",     "Home":"home",           "End":"end",
        "Prior":"pageup",    "Next":"pagedown",       "Insert":"insert",
        "Print":"printscreen","Pause":"pause",        "Caps_Lock":"capslock",
        "Num_Lock":"numlock","Scroll_Lock":"scrolllock",
        "Super_L":"win",     "Super_R":"win",
        "Alt_L":"alt",       "Alt_R":"alt",
        "Control_L":"ctrl",  "Control_R":"ctrl",
        "Shift_L":"shift",   "Shift_R":"shift",
        "KP_Enter":"enter",  "KP_Add":"add",          "KP_Subtract":"subtract",
        "KP_Multiply":"multiply","KP_Divide":"divide","KP_Decimal":"decimal",
        **{f"KP_{i}":f"num{i}" for i in range(10)},
        **{f"F{i}":f"f{i}" for i in range(1,25)},
    }

    _ONLY_MODS = {
        "Alt_L","Alt_R","Control_L","Control_R","Shift_L","Shift_R",
        "Super_L","Super_R","Caps_Lock","Num_Lock","Scroll_Lock",
        "Meta_L","Meta_R","ISO_Level3_Shift",
    }

    def _map_key(self, tk_key):
        mapping = {
            "Control_L": "ctrl", "Control_R": "ctrl",
            "Shift_L": "shift", "Shift_R": "shift",
            "Alt_L": "alt", "Alt_R": "alt",
            "Caps_Lock": "caps_lock",
            "Tab": "tab", "Return": "enter", "BackSpace": "backspace",
            "Escape": "esc", "Space": "space",
            "Delete": "delete", "Insert": "insert",
            "Home": "home", "End": "end",
            "Prior": "page_up", "Next": "page_down",
            "Left": "left", "Right": "right", "Up": "up", "Down": "down",
            "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4", "F5": "f5",
            "F6": "f6", "F7": "f7", "F8": "f8", "F9": "f9", "F10": "f10",
            "F11": "f11", "F12": "f12",
            "Print": "prtscr", "Scroll_Lock": "scroll_lock", "Pause": "pause",
            "Windows": "win", "Super_L": "win", "Super_R": "win",
        }
        return mapping.get(tk_key, tk_key.lower() if len(tk_key) == 1 else tk_key)

    def _on_key_press(self, e):
        if self._capturing and self._enabled:
            key = self._map_key(e.keysym)
            self.client.send_key_down(key)

    def _on_key_release(self, e):
        if self._capturing and self._enabled:
            key = self._map_key(e.keysym)
            self.client.send_key_up(key)

    # ── Disconnect ────────────────────────────────────────────────────────

    def _on_disconnected(self):
        self.after(0, lambda: self._cstatus.config(
            text="Desconectado", fg=C["error"]))

    def _close(self):
        self._enabled = False
        try: self.client.disconnect()
        except Exception: pass
        self.destroy()

    # ── Special keys (stubs) ──────────────────────────────────────────────

    def _send_alt_tab(self):
        self.client.send_key_down("alt")
        self.client.send_key_down("tab")
        self.client.send_key_up("tab")
        self.client.send_key_up("alt")

    def _send_win(self):
        self.client.send_key_down("win")
        self.client.send_key_up("win")

    def _send_cad(self):
        self.client.send_key_down("ctrl")
        self.client.send_key_down("alt")
        self.client.send_key_down("delete")
        self.client.send_key_up("delete")
        self.client.send_key_up("alt")
        self.client.send_key_up("ctrl")

    def _send_prtscr(self):
        self.client.send_key_down("printscreen")
        self.client.send_key_up("printscreen")

    def _update_fps(self):
        if self._enabled:
            now = time.time()
            elapsed = now - self._fts
            if elapsed >= 1.0:
                fps = self._fc / elapsed
                self._fps_lbl.config(text=f"{fps:.0f} fps")
                self._fc = 0
                self._fts = now
            self.after(500, self._update_fps)


# ── Main App ───────────────────────────────────────────────────────────────────

class RemoteLinkApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RemoteLink")
        self.geometry("980x680")
        self.minsize(800, 560)
        self.configure(bg=C["bg_surface"])
        try:
            self.iconbitmap("assets/icon.ico")
        except Exception:
            pass
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
        body = tk.Frame(self, bg=C["bg_surface"])
        body.pack(fill="both", expand=True)

        # Nav sidebar
        nav = tk.Frame(body, bg=C["nav_bg"], width=180)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Frame(nav, height=10, bg=C["nav_bg"]).pack()

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

        self.server.on_client_connect    = _on_connect
        self.server.on_client_disconnect = _on_disconnect
        self.server.on_status_change     = _on_status

        # Nav items
        self._navitems = {}
        for key, label in [
            ("connect", "Conectar"),
            ("share",   "Compartilhar"),
        ]:
            ni = NavItem(nav, label,
                         command=lambda k=key: self._show(k))
            ni.pack(fill="x", padx=8, pady=1)
            self._navitems[key] = ni

        # Footer
        tk.Frame(nav, bg=C["nav_bg"]).pack(fill="y", expand=True)
        Divider(nav).pack(fill="x", padx=8)
        tk.Label(nav, text="RemoteLink v1.0",
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
        method = info.get("method", "ip")
        ip     = info.get("ip")
        code   = (info.get("code") or "").strip().upper()

        if method == "access_code" and not ip:
            if is_own_code(code):
                messagebox.showerror("Restricao", "Voce nao pode se conectar ao seu proprio codigo de acesso.")
                return
            self._connect_by_code(code)
            return

        if not ip:
            messagebox.showerror("Erro de Conexao",
                "Nao foi possivel resolver o endereco IP.\n\n"
                "Certifique-se que o RemoteLink esta rodando no alvo\n"
                "e que ambos estao na mesma rede.")
            return

        # Impede conexao com a propria maquina
        if is_local_target(ip):
            messagebox.showerror("Restricao", "Nao e possivel conectar ao seu proprio IP.\n\nInsira o IP, hostname ou codigo de outro computador.")
            return

        def on_error(msg):
            self.after(0, lambda m=msg: messagebox.showerror("Erro de Conexao", m))

        self.client = RemoteLinkClient(
            on_status_change=lambda s: None,
            on_error=on_error,
        )

        def run():
            hostname = info.get("hostname", "")

            ips_to_try = [ip]
            if method == "hostname" and hostname:
                for extra_ip in resolve_hostname_to_ips(hostname):
                    if extra_ip not in ips_to_try:
                        ips_to_try.append(extra_ip)

            send_code = code if method == "access_code" else ""

            for try_ip in ips_to_try:
                ok = self.client.connect(
                    ip=try_ip,
                    access_code=send_code,
                    local_access_code=self.machine_info["access_code"],
                )
                if ok:
                    rinfo = self.client.remote_info or {}
                    rinfo["ip"]       = try_ip
                    rinfo["hostname"] = hostname or rinfo.get("hostname", try_ip)
                    self.after(0, lambda r=rinfo: self._open_viewer(r))
                    return

            self.client = None

        threading.Thread(target=run, daemon=True, name="RL-Connect").start()

    def _connect_by_code(self, code: str):
        from tkinter import messagebox as mb

        prog_win = tk.Toplevel(self)
        prog_win.title("Buscando maquina...")
        prog_win.geometry("360x120")
        prog_win.resizable(False, False)
        prog_win.configure(bg=C["bg_surface"])
        prog_win.grab_set()
        prog_win.transient(self)

        tk.Label(prog_win, text=f"Procurando codigo {code} na rede...",
                 font=FONT_UI, bg=C["bg_surface"], fg=C["text"]).pack(pady=(20, 8))
        bar = ttk.Progressbar(prog_win, mode="indeterminate",
                              style="Horizontal.TProgressbar")
        bar.pack(fill="x", padx=30, pady=(0, 8))
        bar.start(12)
        status_lbl = tk.Label(prog_win, text="Escaneando...",
                              font=FONT_UI_SM, bg=C["bg_surface"],
                              fg=C["text_secondary"])
        status_lbl.pack()

        found_event = threading.Event()
        result = {"ip": None, "info": None, "cancelled": False}

        def cancel():
            result["cancelled"] = True
            found_event.set()
            prog_win.destroy()

        prog_win.protocol("WM_DELETE_WINDOW", cancel)

        def scan_and_try():
            from core.client import probe_target
            from core.identity import NetworkScanner, get_all_local_ips

            my_ips = set(get_all_local_ips())

            def on_found(machine):
                if found_event.is_set() or result["cancelled"]:
                    return
                ip = machine["ip"]
                try:
                    prog_win.after(0, lambda: status_lbl.config(
                        text=f"Testando {ip}..."))
                except Exception:
                    return
                from core.client import RemoteLinkClient
                test_client = RemoteLinkClient()
                ok = test_client.connect(ip=ip, access_code=code)
                if ok:
                    result["ip"]   = ip
                    result["info"] = test_client.remote_info or {}
                    result["info"]["ip"] = ip
                    result["client"] = test_client
                    found_event.set()
                else:
                    test_client.disconnect()

            def on_done(found_list):
                found_event.set()

            scanner = NetworkScanner(
                on_found=on_found,
                on_done=on_done,
                max_workers=80,
                timeout=0.4,
            )
            scanner.start()
            found_event.wait(timeout=45)

            if result["cancelled"]:
                return

            try:
                prog_win.destroy()
            except Exception:
                pass

            if result["ip"] and not result["cancelled"]:
                self.client = result["client"]
                rinfo = result["info"]
                self.after(0, lambda: self._open_viewer(rinfo))
            else:
                self.after(0, lambda: mb.showerror(
                    "Codigo nao encontrado",
                    f"Nenhuma maquina com o codigo {code} foi encontrada na rede.\n\n"
                    "Verifique se:\n"
                    "- O RemoteLink esta aberto no computador alvo\n"
                    "- Ambos estao na mesma rede (LAN/WiFi)\n"
                    "- O codigo esta correto"
                ))

        threading.Thread(target=scan_and_try, daemon=True, name="RL-CodeScan").start()

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
