#!/usr/bin/env bash
# Buduje pełny łańcuch dystrybucji: PyInstaller -> .deb -> AppImage.
# Na końcu w katalogu dist/ zostają WYŁĄCZNIE gotowe pliki do rozdania
# (steamtools_<wersja>_amd64.deb, SteamTools-x86_64.AppImage) - wszystkie
# pośrednie artefakty (build/, rozpakowana binarka PyInstaller) są sprzątane.
#
# Ten skrypt SAM aktywuje .venv (nie trzeba robić `source .venv/bin/activate`
# ręcznie przed odpaleniem) - spójnie z tym, jak działa run.sh. Jeśli .venv
# w ogóle nie istnieje, odsyła do venv.sh, tak samo jak run.sh.
#
# Wewnętrznie woła packaging/build_deb.sh i packaging/build_appimage.sh -
# te dwa skrypty NIE są zbędne mimo istnienia build.sh: build.sh to warstwa
# orkiestrująca (aktywacja .venv, kolejność kroków, sprzątanie), a
# packaging/*.sh to warstwa robocza (jak dokładnie zbudować .deb/AppImage
# z gotowej binarki PyInstaller) - można je też wywołać osobno przy
# debugowaniu jednego konkretnego kroku, patrz README.md.
#
# Użycie:
#   ./build.sh [wersja]
#
# Domyślna wersja to 0.1.0, tak samo jak w packaging/build_deb.sh.
set -euo pipefail

VERSION="${1:-0.1.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYINSTALLER_DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build"
RELEASE_DIR="${ROOT_DIR}/dist"
VENV_DIR="${ROOT_DIR}/.venv"

echo "==> Sprawdzanie środowiska .venv"
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
        echo "BŁĄD: środowisko .venv nie istnieje."
        echo ""
        echo "Uruchom najpierw:"
        echo "  ./venv.sh"
        echo "  ./build.sh ${VERSION}"
        exit 1
    fi
    echo "    Aktywuję .venv..."
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
fi
echo "OK - .venv aktywne (${VIRTUAL_ENV})"

echo ""
echo "==> Czyszczenie katalogów build/ i dist/ sprzed poprzedniego builda"
rm -rf "${BUILD_DIR}"
rm -rf "${PYINSTALLER_DIST_DIR}"

echo ""
echo "==> Krok 1/3: PyInstaller (packaging/steamtools.spec)"
pyinstaller "${ROOT_DIR}/packaging/steamtools.spec" --noconfirm

echo ""
echo "==> Krok 2/3: Pakiet .deb"
"${ROOT_DIR}/packaging/build_deb.sh" "${VERSION}"
DEB_FILE="${BUILD_DIR}/deb/steamtools_${VERSION}_amd64.deb"

echo ""
echo "==> Krok 3/3: AppImage"
"${ROOT_DIR}/packaging/build_appimage.sh"
APPIMAGE_FILE="${BUILD_DIR}/appimage/SteamTools-x86_64.AppImage"

echo ""
echo "==> Sprzątanie i przenoszenie gotowych plików do dist/"
# W tym momencie dist/ wciąż zawiera rozpakowaną binarkę PyInstaller
# (dist/steamtools/) - była potrzebna jako input dla obu kroków wyżej.
# Teraz, gdy .deb i AppImage są już zbudowane (w build/, nie w dist/),
# czyścimy dist/ do zera i wkładamy tam WYŁĄCZNIE gotowe pliki końcowe.
rm -rf "${PYINSTALLER_DIST_DIR}"
mkdir -p "${RELEASE_DIR}"

if [[ -f "${DEB_FILE}" ]]; then
    cp "${DEB_FILE}" "${RELEASE_DIR}/"
    echo "  -> dist/$(basename "${DEB_FILE}")"
    RELEASE_DEB_FILE="${RELEASE_DIR}/$(basename "${DEB_FILE}")"
else
    echo "  UWAGA: nie znaleziono ${DEB_FILE}, pomijam."
    RELEASE_DEB_FILE=""
fi

if [[ -f "${APPIMAGE_FILE}" ]]; then
    cp "${APPIMAGE_FILE}" "${RELEASE_DIR}/"
    echo "  -> dist/$(basename "${APPIMAGE_FILE}")"
    chmod +x "${RELEASE_DIR}/$(basename "${APPIMAGE_FILE}")"
else
    echo "  UWAGA: nie znaleziono ${APPIMAGE_FILE}, pomijam."
fi

# Artefakty pośrednie (build/ - zawiera m.in. rozpakowany .AppDir, folder
# roboczy PyInstaller z warn-*.txt/xref-*.html, oraz strukturę pakietu .deb
# przed spakowaniem) nie są już potrzebne - jedyne co ma zostać to gotowe
# pliki w dist/.
rm -rf "${BUILD_DIR}"

echo ""
echo "==> Gotowe. Zawartość dist/:"
ls -la "${RELEASE_DIR}"

if [[ -n "${RELEASE_DEB_FILE}" && -f "${RELEASE_DEB_FILE}" ]]; then
    echo ""
    # Domyślnie Tak - sam Enter (odpowiedź pusta) też instaluje, bo to
    # najczęstsza ścieżka po lokalnym buildzie ("zbuduj i od razu wgraj
    # na tę maszynę do testu"). Jedyne co blokuje instalację to jawne
    # N/n. sudo jest tu wymagane przez dpkg (instalacja systemowa do
    # /usr) - user zostanie zapytany o hasło przez samo sudo, nie trzeba
    # tego dublować w tym skrypcie.
    read -r -p "Zainstalować teraz $(basename "${RELEASE_DEB_FILE}") przez dpkg? [T/n] " INSTALL_ANSWER
    case "${INSTALL_ANSWER,,}" in
        n|nie|no)
            echo "Pomijam instalację."
            ;;
        *)
            echo "==> Instaluję: sudo dpkg --install ${RELEASE_DEB_FILE}"
            sudo dpkg --install "${RELEASE_DEB_FILE}"
            ;;
    esac
fi
