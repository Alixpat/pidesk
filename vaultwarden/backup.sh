#!/bin/bash
set -euo pipefail

TAG="backup-vaultwarden"
BACKUP_DIR="/tmp/vaultwarden-backup"
REMOTE_HOST="<USER>@<BACKUP_HOST>"
REMOTE_DIR="<BACKUP_DIR>"
DB="/home/alex/pidesk/vaultwarden/data/db.sqlite3"
DATE=$(date +%F)

logger -t "$TAG" "Début de la sauvegarde"

mkdir -p "$BACKUP_DIR"

if ! sqlite3 "$DB" ".backup '$BACKUP_DIR/db-$DATE.sqlite3'"; then
    logger -t "$TAG" "ERREUR : échec sqlite3 backup"
    exit 1
fi

if ! rsync -az "$BACKUP_DIR/db-$DATE.sqlite3" "$REMOTE_HOST:$REMOTE_DIR/db-$DATE.sqlite3"; then
    logger -t "$TAG" "ERREUR : échec rsync"
    rm -rf "$BACKUP_DIR"
    exit 1
fi

rm -rf "$BACKUP_DIR"

ssh "$REMOTE_HOST" "ls -1t $REMOTE_DIR/db-*.sqlite3 | tail -n +8 | xargs -r rm --"

logger -t "$TAG" "Sauvegarde terminée avec succès"
