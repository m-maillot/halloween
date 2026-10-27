#!/usr/bin/env bash
# Sauvegarde et restauration du dossier de données (configuration, scénarios, déclencheurs, images,
# code de verrouillage, jeton d'API). Les journaux ne sont pas sauvegardés.
#
#   deploy/backup.sh [--out DOSSIER]       crée halloween-sauvegarde-AAAAMMJJ-HHMMSS.tar.gz
#   sudo deploy/backup.sh --restore FICHIER  arrête le service, remplace les données, le relance
#
# Le fichier contient des SECRETS (jeton Home Assistant, jeton d'API, empreinte du code) : droits 600,
# à garder hors du dépôt et des disques partagés.
# Variables : DATA_DIR (/var/lib/halloween), SERVICE (halloween-engine), SERVICE_USER (halloween),
# SYSTEMCTL (systemctl).
set -euo pipefail

DATA_DIR="${DATA_DIR:-/var/lib/halloween}"
SERVICE="${SERVICE:-halloween-engine}"
SERVICE_USER="${SERVICE_USER:-halloween}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"

OUT="."
RESTORE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="${2:?--out attend un dossier}"; shift 2 ;;
    --restore) RESTORE="${2:?--restore attend un fichier}"; shift 2 ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "option inconnue : $1" >&2; exit 2 ;;
  esac
done

PARENT="$(dirname "$DATA_DIR")"
NAME="$(basename "$DATA_DIR")"

if [ -z "$RESTORE" ]; then
  [ -f "$DATA_DIR/config.json" ] || { echo "Aucune donnée à sauvegarder dans $DATA_DIR (config.json absent)." >&2; exit 1; }
  mkdir -p "$OUT"
  FILE="$OUT/halloween-sauvegarde-$(date +%Y%m%d-%H%M%S).tar.gz"
  # Le moteur écrit chaque fichier de façon atomique : une copie à chaud reste cohérente fichier par fichier.
  ( umask 077; tar -C "$PARENT" -czf "$FILE" --exclude="$NAME/logs" "$NAME" )
  chmod 600 "$FILE"
  echo "Sauvegarde : $FILE ($(du -h "$FILE" | cut -f1))"
  echo "Attention : elle contient les jetons et l'empreinte du code ; ne la partagez pas."
  exit 0
fi

# --- restauration
[ -f "$RESTORE" ] || { echo "Fichier introuvable : $RESTORE" >&2; exit 1; }
if ! tar -tzf "$RESTORE" | grep -q "^$NAME/config.json$"; then
  echo "Ce fichier n'est pas une sauvegarde Halloween (pas de $NAME/config.json)." >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ] && [ ! -w "$PARENT" ]; then
  echo "À lancer en root : sudo $0 --restore $RESTORE" >&2
  exit 1
fi

echo "Arrêt du service $SERVICE"
"$SYSTEMCTL" stop "$SERVICE" || true
if [ -d "$DATA_DIR" ]; then
  KEEP="$DATA_DIR.avant-restauration-$(date +%Y%m%d-%H%M%S)"
  mv "$DATA_DIR" "$KEEP"
  echo "Données actuelles conservées dans $KEEP"
fi
tar -C "$PARENT" -xzf "$RESTORE"
if [ "$(id -u)" -eq 0 ] && id "$SERVICE_USER" >/dev/null 2>&1; then
  chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
fi
chmod 750 "$DATA_DIR"
echo "Redémarrage du service $SERVICE"
"$SYSTEMCTL" start "$SERVICE"
echo "Restauration terminée : $RESTORE"
