#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${TH_REPO_URL:-https://github.com/power0matin/trusthost-telegram-bot.git}"
REF="${TH_REF:-main}"
APP_DIR="${TH_DIR:-/opt/trusthost-telegram-bot}"
BASE_URL="${TRUSTHOST_BASE_URL:-https://my.trusthost.co/api/v1}"
LANG_DEFAULT="${DEFAULT_LANGUAGE:-en}"
LOG="/var/log/trusthost-bot-install.log"
ENV_FILE="$APP_DIR/.env"
ACTION="install"
RECONFIGURE="${RECONFIGURE:-0}"

usage() {
  cat <<USAGE
TrustHost Telegram Bot installer

Usage: install.sh [--reconfigure | --uninstall | --help]

  (no option)    install, or update to the latest version of \$TH_REF
  --reconfigure  ask for the keys again and rewrite .env
  --uninstall    stop the containers (keeps .env and database volume)

Environment (all optional):
  TH_DIR, TH_REF, TH_REPO_URL, TRUSTHOST_BASE_URL, DEFAULT_LANGUAGE (en|fa)
  TRUSTHOST_API_KEY, TRUSTHOST_API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS
  (when all four are set, no prompt is shown)
USAGE
}

case "${1:-}" in
  "") ;;
  --reconfigure) RECONFIGURE=1 ;;
  --uninstall|uninstall) ACTION="uninstall" ;;
  -h|--help) usage; exit 0 ;;
  *) usage; exit 1 ;;
esac

die() { echo "ERROR: $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "Run as root (use sudo)."

touch "$LOG" && chmod 640 "$LOG"
exec > >(tee -a "$LOG") 2>&1
trap 'echo "FAILED at line $LINENO. Log: $LOG"' ERR

HAVE_TTY=0
if (: </dev/tty) 2>/dev/null; then HAVE_TTY=1; fi

if [ "$ACTION" = "uninstall" ]; then
  [ -d "$APP_DIR" ] || die "$APP_DIR not found."
  cd "$APP_DIR" && docker compose down
  echo "Stopped. Configuration ($ENV_FILE) and database volume were kept."
  echo "Remove everything: cd $APP_DIR && docker compose down -v && cd / && rm -rf $APP_DIR"
  exit 0
fi

case "$LANG_DEFAULT" in en|fa) ;; *) die "DEFAULT_LANGUAGE must be en or fa" ;; esac

ask() {
  local name="$1" prompt="$2" secret="${3:-0}" val="${!1:-}"
  if [ -z "$val" ]; then
    [ "$HAVE_TTY" = 1 ] || die "$name is required and no terminal is available. Export it and re-run."
    if [ "$secret" = 1 ]; then
      read -rsp "$prompt: " val </dev/tty
      echo >/dev/tty
    else
      read -rp "$prompt: " val </dev/tty
    fi
  fi
  printf -v "$name" '%s' "$val"
}

envget() { grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2-; }

echo "== 1/6 packages"
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq git curl ca-certificates openssl >/dev/null
fi
for bin in git curl openssl; do
  command -v "$bin" >/dev/null || die "$bin is required."
done

echo "== 2/6 docker"
if ! command -v docker >/dev/null; then
  command -v apt-get >/dev/null || die "Install Docker manually, then re-run."
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true
if ! docker compose version >/dev/null 2>&1; then
  command -v apt-get >/dev/null || die "Docker Compose v2 plugin is required."
  apt-get install -y -qq docker-compose-plugin >/dev/null 2>&1 || apt-get install -y -qq docker-compose-v2 >/dev/null
fi
docker compose version

echo "== 3/6 source ($REF)"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --depth 1 origin "$REF"
  git -C "$APP_DIR" reset --hard FETCH_HEAD
elif [ -e "$APP_DIR" ]; then
  die "$APP_DIR exists and is not a git checkout."
else
  git clone --depth 1 --branch "$REF" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "== 4/6 configuration"
if [ ! -f "$ENV_FILE" ] || [ "$RECONFIGURE" = "1" ]; then
  ask TRUSTHOST_API_KEY "TrustHost API key (th_res_...)"
  ask TRUSTHOST_API_SECRET "TrustHost API secret (th_sec_..., hidden)" 1
  ask TELEGRAM_BOT_TOKEN "Telegram bot token (hidden)" 1
  ask ADMIN_TELEGRAM_IDS "Admin Telegram numeric ID(s), comma-separated"

  [[ "$TRUSTHOST_API_KEY" =~ ^th_res_[A-Za-z0-9]+$ ]] || die "API key must look like th_res_..."
  [[ "$TRUSTHOST_API_SECRET" =~ ^th_sec_[A-Za-z0-9]+$ ]] || die "API secret must look like th_sec_..."
  [[ "$TELEGRAM_BOT_TOKEN" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]] || die "Bot token format is invalid."
  [[ "$ADMIN_TELEGRAM_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]] || die "Admin IDs must be numeric, comma-separated."

  PGPASS="$(openssl rand -hex 24)"
  (
    umask 077
    cat > "$ENV_FILE" <<ENVFILE
TRUSTHOST_BASE_URL=$BASE_URL
TRUSTHOST_API_KEY=$TRUSTHOST_API_KEY
TRUSTHOST_API_SECRET=$TRUSTHOST_API_SECRET
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
ADMIN_TELEGRAM_IDS=$ADMIN_TELEGRAM_IDS
POSTGRES_USER=trusthost
POSTGRES_PASSWORD=$PGPASS
POSTGRES_DB=trusthost_bot
DATABASE_URL=postgresql+asyncpg://trusthost:$PGPASS@postgres:5432/trusthost_bot
LOG_LEVEL=INFO
LOG_JSON=true
TRUSTHOST_MAX_REQUESTS_PER_MINUTE=50
TRUSTHOST_TIMEOUT_SECONDS=15
NOTIFICATION_POLL_MINUTES=5
DEFAULT_LANGUAGE=$LANG_DEFAULT
ENVFILE
  )
  unset TRUSTHOST_API_KEY TRUSTHOST_API_SECRET TELEGRAM_BOT_TOKEN PGPASS
else
  echo "Using existing $ENV_FILE (run with --reconfigure to change it)"
fi
chmod 600 "$ENV_FILE"

echo "== 5/6 connectivity"
echo "Server public IP: $(curl -4 -s -m 8 https://api.ipify.org || echo unknown)"
tg="$(printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$(envget TELEGRAM_BOT_TOKEN)" | curl -s -m 15 -K - 2>/dev/null || true)"
if echo "$tg" | grep -q '"ok":true'; then
  echo "Telegram: OK ($(echo "$tg" | grep -o '"username":"[^"]*"' | head -n1))"
else
  echo "Telegram: FAILED (bad token, or api.telegram.org is blocked from this server)"
fi
code="$(printf 'header = "X-Reseller-Key: %s"\nheader = "X-Reseller-Secret: %s"\n' "$(envget TRUSTHOST_API_KEY)" "$(envget TRUSTHOST_API_SECRET)" \
  | curl -s -m 15 -o /dev/null -w '%{http_code}' -K - "$(envget TRUSTHOST_BASE_URL)/wallet" 2>/dev/null || true)"
echo "TrustHost API GET /wallet: HTTP ${code:-000}  (200 ok, 401/403 bad key or IP not allowed, 000 unreachable)"

echo "== 6/6 start"
docker compose up -d --build
sleep 12
state="$(docker compose ps --format '{{.Service}} {{.State}}' | awk '$1=="bot"{print $2}')"
docker compose ps
docker compose logs --tail=60 bot
[ "$state" = "running" ] || die "Bot container is '$state'. See the logs above."

cat <<DONE

Installed. Log: $LOG
Test in Telegram: /start, then /health, /wallet, /servers
Logs:      cd $APP_DIR && docker compose logs -f bot
Update:    curl -fsSL https://raw.githubusercontent.com/power0matin/trusthost-telegram-bot/main/install.sh | sudo bash
Reconfig:  sudo bash $APP_DIR/install.sh --reconfigure
Uninstall: sudo bash $APP_DIR/install.sh --uninstall
DONE