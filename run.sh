#!/usr/bin/env bash
# Uruchamia SteamTools. Jeśli .venv nie istnieje, pyta użytkownika i
# odsyła do venv.sh zamiast instalować cokolwiek automatycznie.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Środowisko .venv nie istnieje lub jest niekompletne."
    read -r -p "Czy chcesz je teraz utworzyć uruchamiając ./venv.sh? [t/N] " answer
    case "${answer}" in
        [tT]|[tT][aA][kK]|[yY]|[yY][eE][sS])
            "${ROOT_DIR}/venv.sh"
            ;;
        *)
            echo "Anulowano. Uruchom ręcznie: ./venv.sh"
            exit 1
            ;;
    esac
fi

cd "${ROOT_DIR}"
exec "${VENV_PYTHON}" -m steamtools.app "$@"
