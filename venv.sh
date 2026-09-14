#!/usr/bin/env bash
# Tworzy .venv/ i instaluje zależności z requirements.txt.
# Sprawdza też obecność libsteam_api.so - jeśli brak, podaje link do
# pobrania (i próbuje otworzyć go w przeglądarce).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
REQUIREMENTS="${ROOT_DIR}/requirements.txt"
STEAM_LIB="${ROOT_DIR}/steamtools/vendor/linux64/libsteam_api.so"
STEAMWORKS_SDK_URL="https://partner.steamgames.com/downloads/steamworks_sdk.zip"

echo "==> Tworzenie środowiska wirtualnego w ${VENV_DIR}"

if [[ -d "${VENV_DIR}" ]]; then
    echo "    .venv już istnieje - pomijam tworzenie, doinstaluję/zaktualizuję zależności."
else
    python3 -m venv "${VENV_DIR}"
    echo "    Utworzono .venv"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "==> Aktualizacja pip"
pip install --upgrade pip -q

echo "==> Instalacja zależności z requirements.txt"
pip install -r "${REQUIREMENTS}"

deactivate

echo ""
echo "==> Sprawdzanie Steamworks SDK (libsteam_api.so)"

if [[ -f "${STEAM_LIB}" ]]; then
    echo "    OK: znaleziono ${STEAM_LIB}"
else
    echo "    BRAK: ${STEAM_LIB}"
    echo ""
    echo "    Steamworks SDK nie jest dołączony do repo (licencja Valve)."
    echo "    Pobierz go samodzielnie z konta partnerskiego Valve, a następnie"
    echo "    skopiuj plik:"
    echo "        sdk/redistributable_bin/linux64/libsteam_api.so"
    echo "    do:"
    echo "        ${STEAM_LIB}"
    echo ""
    echo "    Link do pobrania:"
    echo "        ${STEAMWORKS_SDK_URL}"
    echo ""

    # Próba otwarcia linku w przeglądarce (najpopularniejsze polecenia na Linuksie).
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "${STEAMWORKS_SDK_URL}" >/dev/null 2>&1 &
        echo "    -> Otworzono link w przeglądarce (xdg-open)."
    elif command -v gio >/dev/null 2>&1; then
        gio open "${STEAMWORKS_SDK_URL}" >/dev/null 2>&1 &
        echo "    -> Otworzono link w przeglądarce (gio open)."
    else
        echo "    Nie znaleziono xdg-open/gio - otwórz link ręcznie."
    fi
fi

echo ""
echo "==> Gotowe. Uruchom aplikację przez: ./run.sh"
