#!/usr/bin/env bash
# Installe (ou met à jour) le moteur Halloween comme service systemd sur le Raspberry Pi.
#
#   sudo deploy/install.sh              installe / met à jour et (re)démarre le service
#   sudo deploy/install.sh --uninstall  arrête et retire le service (les données sont conservées)
#   deploy/install.sh --dry-run         affiche ce qui serait fait, sans rien modifier
#
# Relançable sans risque : ni la configuration ni les données existantes ne sont écrasées.
# Variables : OPT_DIR (/opt/halloween), DATA_DIR (/var/lib/halloween), ETC_DIR (/etc/halloween),
# UNIT_DIR (/etc/systemd/system), SERVICE_USER (halloween), PYTHON (python3).
set -euo pipefail

OPT_DIR="${OPT_DIR:-/opt/halloween}"
DATA_DIR="${DATA_DIR:-/var/lib/halloween}"
ETC_DIR="${ETC_DIR:-/etc/halloween}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
SERVICE_USER="${SERVICE_USER:-halloween}"
PYTHON="${PYTHON:-python3}"
SERVICE=halloween-engine

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"

DRY_RUN=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "option inconnue : $arg" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '+ %s\n' "$*"
  else
    "$@"
  fi
}

step() { printf '\n==> %s\n' "$*"; }

if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  echo "À lancer en root : sudo $0 $*" >&2
  exit 1
fi

if [ "$UNINSTALL" -eq 1 ]; then
  step "Arrêt et retrait du service"
  run systemctl disable --now "$SERVICE" || true
  run rm -f "$UNIT_DIR/$SERVICE.service"
  run systemctl daemon-reload
  echo "Service retiré. Conservés : $DATA_DIR (données), $OPT_DIR (programme), $ETC_DIR."
  exit 0
fi

step "Compte de service '$SERVICE_USER' (accès GPIO par le groupe gpio)"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  run useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
if getent group gpio >/dev/null 2>&1 || [ "$DRY_RUN" -eq 1 ]; then
  run usermod -aG gpio "$SERVICE_USER"
else
  echo "Attention : le groupe 'gpio' n'existe pas (pas un Raspberry Pi OS ?)." >&2
fi

step "Programme dans $OPT_DIR/venv (Python $($PYTHON --version 2>&1 | cut -d' ' -f2))"
run install -d -m 0755 "$OPT_DIR"
if [ ! -x "$OPT_DIR/venv/bin/python" ]; then
  run "$PYTHON" -m venv "$OPT_DIR/venv"
fi
run "$OPT_DIR/venv/bin/pip" install --quiet --upgrade pip
run "$OPT_DIR/venv/bin/pip" install --quiet --upgrade "$REPO/engine[pi]"

step "Configuration dans $ETC_DIR et données dans $DATA_DIR"
run install -d -m 0750 -o root -g "$SERVICE_USER" "$ETC_DIR"
if [ ! -e "$ETC_DIR/halloween.env" ]; then
  run install -m 0640 -o root -g "$SERVICE_USER" /dev/null "$ETC_DIR/halloween.env"
  if [ "$DRY_RUN" -eq 0 ]; then
    cat > "$ETC_DIR/halloween.env" <<'ENV'
# Surcharges facultatives du service halloween-engine.
# HALLOWEEN_UI_DIR=/opt/halloween/ui
# HALLOWEEN_API_TOKEN=
# HALLOWEEN_HA_TOKEN=
ENV
  fi
fi
run install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR" "$DATA_DIR/programs"
if [ ! -e "$DATA_DIR/config.json" ]; then
  run install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" \
    "$HERE/config.example.json" "$DATA_DIR/config.json"
  echo "Configuration d'exemple copiée : à adapter (broches, entités Home Assistant)."
fi

step "Service systemd"
run install -m 0644 "$HERE/$SERVICE.service" "$UNIT_DIR/$SERVICE.service"
run systemctl daemon-reload
run systemctl enable "$SERVICE"
run systemctl restart "$SERVICE"

step "Terminé"
echo "État    : systemctl status $SERVICE"
echo "Journal : journalctl -u $SERVICE -f"
echo "Jeton d'API (à saisir dans l'interface) : sudo cat $DATA_DIR/api-token"
