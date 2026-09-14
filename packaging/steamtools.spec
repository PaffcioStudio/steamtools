# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller packaging/steamtools.spec --noconfirm
#
# Uwaga: libsteam_api.so MUSI być obecny w steamtools/vendor/linux64/ przed
# buildem - PyInstaller pakuje go jako binary data, patrz sekcja `binaries`.

import sys
from pathlib import Path

block_cipher = None

# WAŻNE: pliki .spec są wykonywane przez PyInstaller przez exec() w
# specjalnym kontekście, gdzie __file__ NIE jest zdefiniowane (inaczej niż
# w zwykłym module importowanym normalnie). PyInstaller udostępnia zamiast
# tego zmienną globalną SPECPATH - ścieżkę do katalogu, w którym leży ten
# plik .spec (czyli packaging/) - to jest właściwy sposób na ustalenie
# ścieżek względnych w plikach .spec.
project_root = Path(SPECPATH).resolve().parent

vendor_so = project_root / "steamtools" / "vendor" / "linux64" / "libsteam_api.so"
binaries = []
if vendor_so.exists():
    binaries.append((str(vendor_so), "steamtools/vendor/linux64"))

a = Analysis(
    [str(project_root / "steamtools" / "app.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=[
        (str(project_root / "steamtools" / "resources"), "steamtools/resources"),
    ],
    hiddenimports=[
        "qfluentwidgets",
        "qframelesswindow",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# WAŻNE: budujemy w trybie --onedir (EXE + osobny COLLECT), NIE --onefile.
# Bez COLLECT() PyInstaller domyślnie tworzy JEDEN plik wykonywalny, który
# przy KAŻDYM uruchomieniu rozpakowuje się do katalogu tymczasowego (/tmp) -
# to zauważalnie wolniejszy start i utrudnia debugowanie. Tryb --onedir
# (katalog z binarką + wszystkimi zależnymi plikami obok) startuje
# natychmiast i jest tym, czego oczekują packaging/build_deb.sh oraz
# packaging/build_appimage.sh (kopiują cały katalog dist/steamtools/).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="steamtools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # UWAGA: na Linuksie ten parametr NIE ma żadnego efektu - pojedyncze
    # pliki wykonywalne ELF nie mają metadanych ikony jak .exe/.app.
    # Ikonę widoczną w menu/launcherze/pasku zadań zapewnia wyłącznie plik
    # .desktop (Icon=steamtools) + zainstalowane pliki w
    # usr/share/icons/hicolor/<rozmiar>/apps/steamtools.png - patrz
    # packaging/build_deb.sh i packaging/build_appimage.sh. Ten parametr
    # zostaje na wypadek przyszłego builda pod Windows (.ico) lub macOS
    # (.icns), gdzie faktycznie działa.
    icon=str(project_root / "steamtools" / "resources" / "icons" / "steamtools.png")
    if (project_root / "steamtools" / "resources" / "icons" / "steamtools.png").exists()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="steamtools",
)
