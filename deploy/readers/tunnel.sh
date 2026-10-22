#!/bin/sh
set -eu
: "${PLATONUS_SSH_HOST:?Set SSH host}"
: "${PLATONUS_SSH_USER:?Set SSH user}"
: "${PLATONUS_REMOTE_MYSQL_HOST:?Set remote MySQL host}"
exec ssh -N -T -g -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/keys/known_hosts \
  -i /keys/id_key -L "0.0.0.0:6080:${PLATONUS_REMOTE_MYSQL_HOST}:${PLATONUS_REMOTE_MYSQL_PORT:-3306}" \
  "${PLATONUS_SSH_USER}@${PLATONUS_SSH_HOST}"
