#!/bin/bash
# load database and bootstrap credentials from mounted Docker secrets before Keycloak starts
set -eu
export KC_DB_PASSWORD="$(cat /run/secrets/db_password)"
export KC_BOOTSTRAP_ADMIN_PASSWORD="$(cat /run/secrets/admin_password)"
# replace the shell so signals reach Keycloak directly
exec /opt/keycloak/bin/kc.sh start --optimized --import-realm
