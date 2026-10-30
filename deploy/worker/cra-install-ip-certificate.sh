#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG=/etc/cra-acme/config
[[ -r "$CONFIG" ]] || { echo "Missing $CONFIG" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CONFIG"
: "${PUBLIC_IP:?Set PUBLIC_IP in /etc/cra-acme/config}"
python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$PUBLIC_IP"

LEGO_PATH=/var/lib/cra-acme
CERT="$LEGO_PATH/certificates/$PUBLIC_IP.crt"
KEY="$LEGO_PATH/certificates/$PUBLIC_IP.key"
TLS_DIR=/etc/caddy/tls
[[ -s "$CERT" && -s "$KEY" ]] || { echo "ACME certificate files are missing" >&2; exit 1; }
openssl x509 -in "$CERT" -noout -checkip "$PUBLIC_IP" -checkend 3600
cert_pub=$(openssl x509 -in "$CERT" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum | cut -d ' ' -f 1)
key_pub=$(openssl pkey -in "$KEY" -pubout -outform DER | sha256sum | cut -d ' ' -f 1)
[[ "$cert_pub" == "$key_pub" ]] || { echo "Certificate and key do not match" >&2; exit 1; }

install -d -o root -g caddy -m 0750 "$TLS_DIR"
stage=$(mktemp -d /run/cra-cert-install.XXXXXX)
had_cert=0
if [[ -s "$TLS_DIR/fullchain.pem" && -s "$TLS_DIR/privkey.pem" ]]; then
    had_cert=1
    cp -p "$TLS_DIR/fullchain.pem" "$stage/old-fullchain.pem"
    cp -p "$TLS_DIR/privkey.pem" "$stage/old-privkey.pem"
fi
rollback() {
    rc=$?
    trap - EXIT
    if (( rc != 0 )); then
        if (( had_cert == 1 )); then
            install -o root -g caddy -m 0640 "$stage/old-fullchain.pem" "$TLS_DIR/fullchain.pem"
            install -o root -g caddy -m 0640 "$stage/old-privkey.pem" "$TLS_DIR/privkey.pem"
        else
            rm -f "$TLS_DIR/fullchain.pem" "$TLS_DIR/privkey.pem"
        fi
    fi
    rm -rf "$stage"
    exit "$rc"
}
trap rollback EXIT

install -o root -g caddy -m 0640 "$CERT" "$stage/fullchain.pem"
install -o root -g caddy -m 0640 "$KEY" "$stage/privkey.pem"
mv -f "$stage/fullchain.pem" "$TLS_DIR/fullchain.pem"
mv -f "$stage/privkey.pem" "$TLS_DIR/privkey.pem"
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
