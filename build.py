"""
RemoteLink - Build Script
=========================
Gera um executável standalone (.exe) com Python embutido.
O arquivo final roda em qualquer Windows sem Python instalado.

Uso:
    python build.py              # Build padrão (onefile)
    python build.py --onedir     # Build em pasta (mais rápido de iniciar)
    python build.py --debug      # Inclui console para ver erros
    python build.py --clean      # Apenas limpa artefatos anteriores

Requisitos:
    pip install pyinstaller pillow
"""

import subprocess
import sys
import os
import shutil
import argparse
import time
import platform

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
ASSETS = os.path.join(ROOT, "assets")
ICON = os.path.join(ASSETS, "icon.ico")
APP_NAME = "RemoteLink"
VERSION = "1.0.0"


# ── Terminal colors ────────────────────────────────────────────────────────────

def _supports_color():
    return sys.stdout.isatty() and platform.system() != "Windows" or \
           os.environ.get("TERM") == "xterm"

def ok(msg):   print(f"  \033[32m✓\033[0m  {msg}" if _supports_color() else f"  [OK]  {msg}")
def info(msg): print(f"  \033[34m→\033[0m  {msg}" if _supports_color() else f"  [>>]  {msg}")
def warn(msg): print(f"  \033[33m!\033[0m  {msg}" if _supports_color() else f"  [!!]  {msg}")
def err(msg):  print(f"  \033[31m✗\033[0m  {msg}" if _supports_color() else f"  [XX]  {msg}")
def sep():     print("  " + "─" * 56)


# ── Dependency checks ──────────────────────────────────────────────────────────

def check_deps():
    """Ensure PyInstaller and optional packages are available."""
    info("Verificando dependências de build...")

    missing = []
    try:
        import PyInstaller
        ok(f"PyInstaller {PyInstaller.__version__}")
    except ImportError:
        missing.append("pyinstaller")

    try:
        from PIL import Image
        ok(f"Pillow (geração do ícone)")
    except ImportError:
        warn("Pillow não encontrado — ícone não será regenerado")

    if missing:
        err(f"Pacotes faltando: {', '.join(missing)}")
        print(f"\n  Instale com:  pip install {' '.join(missing)}\n")
        sys.exit(1)


# ── Icon generation ────────────────────────────────────────────────────────────

def ensure_icon():
    """Generate icon.ico if it doesn't exist or is outdated."""
    os.makedirs(ASSETS, exist_ok=True)

    if os.path.exists(ICON):
        ok(f"Ícone encontrado: assets/icon.ico")
        return True

    info("Gerando ícone...")
    try:
        from PIL import Image, ImageDraw, ImageFilter

        def make_frame(s):
            img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            pad = max(4, int(s * 0.07))
            r   = int(s * 0.20)

            # Shadow
            sh = Image.new("RGBA", (s, s), (0, 0, 0, 0))
            sd = ImageDraw.Draw(sh)
            sd.rounded_rectangle([pad+2, pad+4, s-pad+2, s-pad+4],
                                  radius=r, fill=(0, 60, 140, 55))
            sh = sh.filter(ImageFilter.GaussianBlur(max(1, int(s * 0.035))))
            img.paste(sh, (0, 0), sh)

            # Background
            d.rounded_rectangle([pad, pad, s-pad, s-pad],
                                 radius=r, fill=(0, 103, 192, 255))
            hl = Image.new("RGBA", (s, s), (0, 0, 0, 0))
            hd = ImageDraw.Draw(hl)
            hd.rounded_rectangle([pad, pad, s-pad, s//2],
                                  radius=r, fill=(50, 150, 230, 70))
            img.paste(hl, (0, 0), hl)

            cx, cy = s // 2, s // 2
            sc = lambda v: max(1, int(s * v))
            mon_w, mon_h = sc(0.21), sc(0.155)
            mon_r = max(2, sc(0.025))
            offset = sc(0.175)
            sy_off = sc(0.005)
            ip = max(1, sc(0.018))

            for sign in (-1, 1):
                mx = cx + sign * offset
                my = cy - sy_off
                x0, y0 = mx - mon_w // 2, my - mon_h // 2
                x1, y1 = mx + mon_w // 2, my + mon_h // 2
                d.rounded_rectangle([x0, y0, x1, y1], radius=mon_r,
                                    fill=(255, 255, 255, 235))
                d.rounded_rectangle([x0+ip, y0+ip, x1-ip, y1-ip],
                                    radius=max(1, mon_r-1),
                                    fill=(190, 220, 255, 220))
                sh2 = sc(0.045)
                bw, bh = sc(0.10), max(2, sc(0.018))
                tw = max(1, sc(0.008))
                d.rectangle([mx-tw, y1, mx+tw, y1+sh2],
                             fill=(240, 240, 240, 200))
                d.rounded_rectangle([mx-bw//2, y1+sh2, mx+bw//2, y1+sh2+bh],
                                    radius=1, fill=(240, 240, 240, 200))

            br = sc(0.09)
            d.ellipse([cx-br-sc(0.015), cy-br-sc(0.015),
                       cx+br+sc(0.015), cy+br+sc(0.015)],
                      fill=(0, 80, 170, 255))
            d.ellipse([cx-br, cy-br, cx+br, cy+br],
                      fill=(255, 255, 255, 255))

            lw   = max(1, sc(0.022))
            el_w = sc(0.055)
            el_h = sc(0.028)
            gap  = sc(0.02)
            li   = Image.new("RGBA", (s, s), (0, 0, 0, 0))
            ld   = ImageDraw.Draw(li)
            for dx, dy in [(-gap, -gap), (gap, gap)]:
                lx, ly = cx + dx, cy + dy
                ld.rounded_rectangle([lx-el_w, ly-el_h, lx+el_w, ly+el_h],
                                     radius=el_h,
                                     outline=(0, 100, 190, 255), width=lw)
            li = li.rotate(45, resample=Image.BICUBIC, center=(cx, cy))
            img.paste(li, (0, 0), li)
            return img

        sizes  = [256, 128, 64, 48, 32, 16]
        frames = [make_frame(sz) for sz in sizes]
        frames[0].save(ICON, format="ICO",
                       sizes=[(sz, sz) for sz in sizes],
                       append_images=frames[1:])
        frames[0].save(os.path.join(ASSETS, "icon_256.png"), format="PNG")
        ok("Ícone gerado: assets/icon.ico")
        return True

    except Exception as e:
        warn(f"Não foi possível gerar o ícone: {e}")
        return False


# ── Clean ──────────────────────────────────────────────────────────────────────

def clean():
    info("Limpando artefatos anteriores...")
    removed = []
    for path in [BUILD, DIST, os.path.join(ROOT, f"{APP_NAME}.spec")]:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed.append(os.path.basename(path))
    if removed:
        ok(f"Removido: {', '.join(removed)}")
    else:
        ok("Nada para limpar")


# ── Build ──────────────────────────────────────────────────────────────────────

def build(onefile=True, debug=False):
    check_deps()
    sep()

    has_icon = ensure_icon()
    sep()

    clean()
    sep()

    info(f"Iniciando build — modo: {'onefile' if onefile else 'onedir'}")
    t0 = time.time()

    # ── PyInstaller arguments ─────────────────────────────────────────────
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",

        # Bundle mode
        "--onefile" if onefile else "--onedir",

        # Window mode — hide console unless debug
        "--windowed" if not debug else "--console",

        # ── Data files (source;dest) ──────────────────────────────────────
        # Separator is ; on Windows, : on Unix
        "--add-data", f"core{os.pathsep}core",
        "--add-data", f"gui{os.pathsep}gui",

        # ── Hidden imports ────────────────────────────────────────────────
        # tkinter (sometimes missed by the hook)
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.font",
        "--hidden-import", "tkinter.messagebox",

        # PIL / Pillow
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageDraw",
        "--hidden-import", "PIL.ImageFilter",
        "--hidden-import", "PIL.ImageTk",

        # Screen capture
        "--hidden-import", "mss",
        "--hidden-import", "mss.windows",
        "--hidden-import", "mss.linux",
        "--hidden-import", "mss.darwin",

        # Input automation
        "--hidden-import", "pyautogui",
        "--hidden-import", "pynput",
        "--hidden-import", "pynput.mouse",
        "--hidden-import", "pynput.keyboard",

        # stdlib used at runtime
        "--hidden-import", "uuid",
        "--hidden-import", "hashlib",
        "--hidden-import", "ipaddress",
        "--hidden-import", "zlib",
        "--hidden-import", "struct",

        # ── Collect entire packages ───────────────────────────────────────
        "--collect-all", "PIL",
        "--collect-all", "mss",
        "--collect-all", "pyautogui",

        # ── Exclude heavy unused packages to reduce size ──────────────────
        "--exclude-module", "numpy",
        "--exclude-module", "scipy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--exclude-module", "cv2",
        "--exclude-module", "tensorflow",
        "--exclude-module", "torch",
        "--exclude-module", "pytest",
        "--exclude-module", "unittest",
        "--exclude-module", "doctest",
        "--exclude-module", "pdb",
        "--exclude-module", "IPython",
        "--exclude-module", "notebook",
        "--exclude-module", "setuptools",
        "--exclude-module", "pip",

        # ── Metadata ──────────────────────────────────────────────────────
        "--version-file", _write_version_file(),
    ]

    # Icon
    if has_icon and os.path.exists(ICON):
        cmd += ["--icon", ICON]
        info(f"Ícone: assets/icon.ico")

    # UPX compression (if available — reduces exe size ~30%)
    upx = shutil.which("upx")
    if upx:
        cmd += ["--upx-dir", os.path.dirname(upx)]
        info(f"UPX encontrado — compressão ativada: {upx}")
    else:
        cmd += ["--noupx"]
        warn("UPX não encontrado — exe não será comprimido (opcional)")

    cmd.append("main.py")

    sep()
    info("Comando PyInstaller:")
    # Pretty-print the command
    cmd_str = " ".join(
        f'"{a}"' if " " in a else a for a in cmd
    )
    print(f"\n    {cmd_str}\n")
    sep()

    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.time() - t0

    if result.returncode != 0:
        sep()
        err("Build FALHOU!")
        err(f"Tempo: {elapsed:.1f}s")
        print("\n  Dicas:")
        print("  • Rode com --debug para ver erros detalhados")
        print("  • Verifique se todas as dependências estão instaladas")
        print("  • pip install pyinstaller pillow mss pyautogui")
        sys.exit(1)

    # ── Post-build ─────────────────────────────────────────────────────────
    sep()

    if onefile:
        exe_name = f"{APP_NAME}.exe" if platform.system() == "Windows" else APP_NAME
        exe_path = os.path.join(DIST, exe_name)
    else:
        exe_name = f"{APP_NAME}.exe" if platform.system() == "Windows" else APP_NAME
        exe_path = os.path.join(DIST, APP_NAME, exe_name)

    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / 1024 / 1024
        ok(f"Build concluído em {elapsed:.1f}s")
        ok(f"Arquivo: {os.path.relpath(exe_path, ROOT)}")
        ok(f"Tamanho: {size_mb:.1f} MB")

        if onefile:
            _print_distribution_guide(exe_path)
        else:
            _print_onedir_guide(os.path.join(DIST, APP_NAME))
    else:
        warn("Build concluído mas o executável não foi encontrado no local esperado")
        info(f"Verifique a pasta: {DIST}")


def _write_version_file() -> str:
    """Write a Windows version info file for the .exe metadata."""
    vfile = os.path.join(BUILD, "version_info.txt")
    os.makedirs(BUILD, exist_ok=True)

    major, minor, patch = VERSION.split(".")
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'RemoteLink'),
         StringStruct(u'FileDescription', u'RemoteLink - Acesso Remoto'),
         StringStruct(u'FileVersion', u'{VERSION}'),
         StringStruct(u'InternalName', u'RemoteLink'),
         StringStruct(u'LegalCopyright', u'MIT License'),
         StringStruct(u'OriginalFilename', u'RemoteLink.exe'),
         StringStruct(u'ProductName', u'RemoteLink'),
         StringStruct(u'ProductVersion', u'{VERSION}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ]
)
"""
    with open(vfile, "w", encoding="utf-8") as f:
        f.write(content)
    return vfile


def _print_distribution_guide(exe_path: str):
    sep()
    print(f"""
  📦 COMO DISTRIBUIR

  O arquivo {os.path.basename(exe_path)} é completamente standalone.
  Inclui o Python {sys.version.split()[0]} e todas as dependências embutidas.

  Para distribuir:
    1. Copie apenas o arquivo  RemoteLink.exe
    2. Cole em qualquer Windows 10/11 — sem instalar nada
    3. Execute diretamente

  ⚠  Na primeira execução o Windows Defender pode alertar
     (arquivo novo, sem assinatura digital). O usuário pode
     clicar em "Mais informações → Executar assim mesmo".

  Para assinar digitalmente (remove o alerta):
    signtool sign /fd SHA256 /t http://timestamp.digicert.com RemoteLink.exe
""")


def _print_onedir_guide(dist_dir: str):
    sep()
    print(f"""
  📦 COMO DISTRIBUIR (modo onedir)

  A pasta  {os.path.basename(dist_dir)}/  contém o executável e todas as DLLs.
  Compacte-a em .zip para distribuir:

    Windows:  Compress-Archive -Path dist\\RemoteLink -DestinationPath RemoteLink.zip
    Linux:    zip -r RemoteLink.zip dist/RemoteLink/

  O usuário extrai o .zip e executa RemoteLink.exe diretamente.
  Não precisa instalar Python.
""")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="RemoteLink Build Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python build.py                 Build onefile (padrão)
  python build.py --onedir        Build em pasta (inicia mais rápido)
  python build.py --debug         Build com console (ver erros)
  python build.py --clean         Apenas limpa artefatos
        """,
    )
    parser.add_argument("--onedir",  action="store_true",
                        help="Gerar pasta em vez de arquivo único")
    parser.add_argument("--debug",   action="store_true",
                        help="Incluir console (útil para debugar)")
    parser.add_argument("--clean",   action="store_true",
                        help="Apenas limpa artefatos e sai")
    parser.add_argument("--version", action="version", version=f"RemoteLink {VERSION}")
    args = parser.parse_args()

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print(f"  ║          RemoteLink Builder  v{VERSION:<24}  ║")
    print(f"  ║          Python {sys.version.split()[0]:<8}  PyInstaller build         ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()

    if args.clean:
        clean()
        return

    build(onefile=not args.onedir, debug=args.debug)


if __name__ == "__main__":
    main()
