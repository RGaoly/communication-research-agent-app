#!/usr/bin/env bash
set -Eeuo pipefail

# lego invokes the pre/deploy/post hooks only when a certificate is issued or
# renewed. A routine check therefore leaves Caddy running without downtime.
CONFIG=/etc/cra-acme/config
[[ -r "$CONFIG" ]] || { echo "Missing $CONFIG" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CONFIG"
: "${PUBLIC_IP:?Set PUBLIC_IP in /etc/cra-acme/config}"
python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$PUBLIC_IP"

LEGO=/usr/local/bin/lego
LEGO_PATH=/var/lib/cra-acme
[[ -x "$LEGO" ]] || { echo "Missing verified lego binary at $LEGO" >&2; exit 2; }

was_active=0
if systemctl is-active --quiet caddy; then
    was_active=1
fi
ensure_caddy() {
    rc=$?
    trap - EXIT
    if (( was_active == 1 )) && ! systemctl is-active --quiet caddy; then
        systemctl start caddy || logger -t cra-acme "failed to restart Caddy after ACME operation"
    fi
    exit "$rc"
}
trap ensure_caddy EXIT

lego run --server https://acme-v02.api.letsencrypt.org/directory \
    --email "${ACME_EMAIL:-}" --accept-tos --path "$LEGO_PATH" \
    --domains "$PUBLIC_IP" --tls --profile shortlived --renew-days 4 \
    --pre-hook "/usr/bin/systemctl stop caddy" \
    --deploy-hook "/usr/local/sbin/cra-install-ip-certificate.sh" \
    --post-hook "/usr/bin/systemctl start caddy"
