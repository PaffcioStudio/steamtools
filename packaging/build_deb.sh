#!/usr/bin/env bash
# Buduje pakiet .deb z wynikowej binarki PyInstaller (dist/steamtools/).
# Wymaga: dpkg-deb (standardowo dostępny w Debianie/Ubuntu/pochodnych, w tym TuxedoOS).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Domyślna wersja z pliku VERSION w korzeniu repo, TEGO SAMEGO co czyta
# ui/views/about_view.py w runtime (core/config.py: get_app_version()) -
# patrz komentarz w build.sh, który normalnie woła ten skrypt i przekazuje
# VERSION dalej jako argument $1.
VERSION="${1:-$(cat "${ROOT_DIR}/VERSION" 2>/dev/null || echo "0.1.0")}"
ARCH="amd64"
PKG_NAME="steamtools"
DIST_DIR="${ROOT_DIR}/dist/steamtools"
BUILD_DIR="${ROOT_DIR}/build/deb"
PKG_DIR="${BUILD_DIR}/${PKG_NAME}_${VERSION}_${ARCH}"

if [[ ! -d "${DIST_DIR}" ]]; then
    echo "Brak ${DIST_DIR} - najpierw uruchom:"
    echo "  pyinstaller packaging/steamtools.spec --noconfirm"
    exit 1
fi

# Walidacja, że binarka faktycznie startuje i nie wysypuje się na
# ModuleNotFoundError - to jest wiarygodny sygnał tego, czy PyInstaller był
# odpalony z aktywnym .venv (gdzie qfluentwidgets jest zainstalowane) czy z
# systemowego PATH (gdzie zwykle go nie ma). Sprawdzanie samej struktury
# plików w _internal/ nie działa niezawodnie - czysty kod Pythona (w tym
# qfluentwidgets) ląduje skompresowany wewnątrz PKG/PYZ dopisanego do
# samego pliku wykonywalnego, nie jako osobny katalog na dysku. Łapanie
# tego TU, przed zbudowaniem .deb, oszczędza czas w porównaniu z odkryciem
# tego dopiero po `dpkg -i` i próbie uruchomienia zainstalowanej aplikacji.
echo "Sprawdzanie, czy binarka startuje poprawnie..."
BINARY_CHECK_OUTPUT=$(QT_QPA_PLATFORM=offscreen timeout 1 "${DIST_DIR}/steamtools" 2>&1 || true)
if echo "${BINARY_CHECK_OUTPUT}" | grep -qi "ModuleNotFoundError\|ImportError"; then
    echo "BŁĄD: spakowana binarka nie startuje - brakujący moduł Pythona."
    echo ""
    echo "${BINARY_CHECK_OUTPUT}" | grep -i "ModuleNotFoundError\|ImportError" | head -3
    echo ""
    echo "To zwykle oznacza, że 'pyinstaller' był uruchomiony BEZ aktywnego"
    echo "środowiska .venv (system wziął pyinstaller/zależności z globalnego"
    echo "PATH, gdzie część zależności projektu nie jest zainstalowana)."
    echo "Napraw przez:"
    echo ""
    echo "  source .venv/bin/activate"
    echo "  rm -rf build dist"
    echo "  pyinstaller packaging/steamtools.spec --noconfirm"
    echo "  ./packaging/build_deb.sh ${VERSION}"
    exit 1
fi
echo "OK - binarka startuje poprawnie."

rm -rf "${BUILD_DIR}"
mkdir -p "${PKG_DIR}/DEBIAN"
mkdir -p "${PKG_DIR}/opt/${PKG_NAME}"
mkdir -p "${PKG_DIR}/usr/bin"
mkdir -p "${PKG_DIR}/usr/share/applications"

# Binarka + wszystkie zależne pliki PyInstaller (folder --onedir)
cp -r "${DIST_DIR}/." "${PKG_DIR}/opt/${PKG_NAME}/"

# Symlink do PATH
ln -sf "/opt/${PKG_NAME}/steamtools" "${PKG_DIR}/usr/bin/steamtools"

# Ikony - pełny zestaw rozdzielczości w strukturze hicolor icon theme
# (freedesktop.org), żeby system wybrał właściwy rozmiar zamiast skalować
# jeden obrazek (menedżer plików, launcher, pasek zadań itd. każdy może
# chcieć innej rozdzielczości).
ICONS_SRC_DIR="${ROOT_DIR}/steamtools/resources/icons"
for size in 16 24 32 48 64 128 256 512; do
    icon_file="${ICONS_SRC_DIR}/steamtools-${size}.png"
    if [[ -f "${icon_file}" ]]; then
        dest_dir="${PKG_DIR}/usr/share/icons/hicolor/${size}x${size}/apps"
        mkdir -p "${dest_dir}"
        cp "${icon_file}" "${dest_dir}/steamtools.png"
    fi
done

# Wpis .desktop
cat > "${PKG_DIR}/usr/share/applications/steamtools.desktop" <<EOF
[Desktop Entry]
Name=SteamTools
Comment=Menedżer osiągnięć i farmienia kart Steam
Exec=/opt/${PKG_NAME}/steamtools
Icon=steamtools
Terminal=false
Type=Application
Categories=Utility;
EOF

# Metadane pakietu
cat > "${PKG_DIR}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: games
Priority: optional
Architecture: ${ARCH}
Maintainer: Paffcio
Depends: libc6, libx11-6, hicolor-icon-theme, libxcb-cursor0
Description: Menedżer osiągnięć i farmienia kart Steam (Linux)
 SteamTools łączy funkcje odblokowywania/edycji osiągnięć Steam oraz
 farmienia kart kolekcjonerskich (card idling) w jednej aplikacji z
 nowoczesnym interfejsem Fluent Design.
EOF

dpkg-deb --build --root-owner-group "${PKG_DIR}"

echo "Gotowe: ${BUILD_DIR}/$(basename "${PKG_DIR}").deb"
