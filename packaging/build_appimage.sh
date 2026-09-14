#!/usr/bin/env bash
# Buduje AppImage z wynikowej binarki PyInstaller (dist/steamtools/).
# Wymaga narzędzia appimagetool - pobieramy je automatycznie przy pierwszym
# uruchomieniu, jeśli nie ma go lokalnie w packaging/tools/.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist/steamtools"
BUILD_DIR="${ROOT_DIR}/build/appimage"
APPDIR="${BUILD_DIR}/SteamTools.AppDir"
TOOLS_DIR="${ROOT_DIR}/packaging/tools"

if [[ ! -d "${DIST_DIR}" ]]; then
    echo "Brak ${DIST_DIR} - najpierw uruchom:"
    echo "  pyinstaller packaging/steamtools.spec --noconfirm"
    exit 1
fi

# Ta sama walidacja co w build_deb.sh - patrz komentarz tam po szczegóły
# (sprawdzanie struktury plików w _internal/ nie działa niezawodnie, czysty
# kod Pythona ląduje skompresowany wewnątrz PKG/PYZ, nie jako osobny
# katalog - jedyny wiarygodny test to faktyczne uruchomienie binarki).
echo "Sprawdzanie, czy binarka startuje poprawnie..."
BINARY_CHECK_OUTPUT=$(QT_QPA_PLATFORM=offscreen timeout 1 "${DIST_DIR}/steamtools" 2>&1 || true)
if echo "${BINARY_CHECK_OUTPUT}" | grep -qi "ModuleNotFoundError\|ImportError"; then
    echo "BŁĄD: spakowana binarka nie startuje - brakujący moduł Pythona."
    echo ""
    echo "${BINARY_CHECK_OUTPUT}" | grep -i "ModuleNotFoundError\|ImportError" | head -3
    echo ""
    echo "To zwykle oznacza, że 'pyinstaller' był uruchomiony BEZ aktywnego"
    echo "środowiska .venv. Napraw przez:"
    echo ""
    echo "  source .venv/bin/activate"
    echo "  rm -rf build dist"
    echo "  pyinstaller packaging/steamtools.spec --noconfirm"
    echo "  ./packaging/build_appimage.sh"
    exit 1
fi
echo "OK - binarka startuje poprawnie."

mkdir -p "${TOOLS_DIR}"
APPIMAGETOOL="${TOOLS_DIR}/appimagetool-x86_64.AppImage"
if [[ ! -x "${APPIMAGETOOL}" ]]; then
    echo "Pobieram appimagetool..."
    curl -L -o "${APPIMAGETOOL}" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "${APPIMAGETOOL}"
fi

rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"

cp -r "${DIST_DIR}/." "${APPDIR}/usr/bin/"

ICONS_SRC_DIR="${ROOT_DIR}/steamtools/resources/icons"
MAIN_ICON="${ICONS_SRC_DIR}/steamtools.png"

if [[ ! -f "${MAIN_ICON}" ]]; then
    echo "Brak ${MAIN_ICON} - wygeneruj ikony (patrz steamtools/resources/icons/)."
    exit 1
fi

# AppImage wymaga ikony w katalogu głównym AppDir (dla samego .desktop
# i miniatury pliku), a dodatkowo instalujemy pełny zestaw rozdzielczości
# do usr/share/icons/hicolor/ - te same rozmiary co w pakiecie .deb, żeby
# zachowanie było spójne niezależnie od formy dystrybucji.
cp "${MAIN_ICON}" "${APPDIR}/steamtools.png"

for size in 16 24 32 48 64 128 256 512; do
    icon_file="${ICONS_SRC_DIR}/steamtools-${size}.png"
    if [[ -f "${icon_file}" ]]; then
        dest_dir="${APPDIR}/usr/share/icons/hicolor/${size}x${size}/apps"
        mkdir -p "${dest_dir}"
        cp "${icon_file}" "${dest_dir}/steamtools.png"
    fi
done

cat > "${APPDIR}/steamtools.desktop" <<EOF
[Desktop Entry]
Name=SteamTools
Comment=Menedżer osiągnięć i farmienia kart Steam
Exec=steamtools
Icon=steamtools
Terminal=false
Type=Application
Categories=Utility;
EOF

cat > "${APPDIR}/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export LD_LIBRARY_PATH="${HERE}/usr/bin:${LD_LIBRARY_PATH:-}"
exec "${HERE}/usr/bin/steamtools" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

"${APPIMAGETOOL}" "${APPDIR}" "${BUILD_DIR}/SteamTools-x86_64.AppImage"

echo "Gotowe: ${BUILD_DIR}/SteamTools-x86_64.AppImage"
