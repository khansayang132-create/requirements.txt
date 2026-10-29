#!/usr/bin/env bash
# Reach the owner's website (served from their phone, published by `bash termux/install.sh site`).
#
#   scripts/site.sh check          is the site up? prints the HTTP status and page title
#   scripts/site.sh get [PATH]     print a page, e.g. scripts/site.sh get /about
#   scripts/site.sh url            print the site's address
#
# Needs SITE_URL (https://name.ngrok-free.app) and, if the site has a password, SITE_AUTH
# (username:password). Set both as secrets in the cloud environment's settings, and add the domain
# under Allowed domains, so every session has them. The password is passed to curl on stdin, so it
# never appears in a process list or a log.
set -euo pipefail

die() { echo "site: $*" >&2; exit 1; }

url=${SITE_URL:-}
[[ -n $url ]] || die "SITE_URL is not set. Add SITE_URL (and SITE_AUTH) as secrets in the cloud environment's settings."
[[ $url == http*://* ]] || url="https://$url"
url=${url%/}

fetch() {  # fetch PATH [extra curl args...]: body on stdout
    local path=$1; shift
    [[ $path == /* ]] || path="/$path"
    {
        # ngrok's free plan shows a warning page to browsers unless this header is sent.
        echo 'header = "ngrok-skip-browser-warning: 1"'
        [[ -n ${SITE_AUTH:-} ]] && printf 'user = "%s"\n' "${SITE_AUTH//\"/\\\"}"
        true
    } | curl -sS -L -m 30 -K - "$@" "$url$path"
}

case ${1:-check} in
    url)
        echo "$url" ;;
    get)
        fetch "${2:-/}" -f ;;
    check)
        tmp=$(mktemp)
        trap 'rm -f "$tmp"' EXIT
        code=$(fetch / -o "$tmp" -w '%{http_code}') || die "could not reach $url (is the domain in Allowed domains, and is the phone online?)"
        title=$(grep -io '<title>[^<]*' "$tmp" | head -n 1 | sed 's/<title>//I' || true)
        case $code in
            2??) echo "UP $code $url${title:+  \"$title\"}" ;;
            401) echo "AUTH $code $url: the password was refused (check SITE_AUTH)"; exit 1 ;;
            404) if grep -qi 'ERR_NGROK_3200\|endpoint .* is offline' "$tmp"; then
                     echo "OFFLINE $url: the phone's tunnel is not running (bash termux/install.sh site)"
                 else echo "UP 404 $url (no page at /)"; fi; exit 1 ;;
            502|503|504) echo "DOWN $code $url: the tunnel is up but the website on the phone is not answering"; exit 1 ;;
            *) echo "DOWN $code $url"; exit 1 ;;
        esac ;;
    *)
        die "use: scripts/site.sh check | get [PATH] | url" ;;
esac
