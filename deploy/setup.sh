#!/usr/bin/env bash
# Server setup for the admin panel. Run as root on the VPS, twice:
#
#   bash setup.sh key       # creates the ggadmin user + deploy key, prints the public key
#   (add that key to github.com/miladdhq/ggmilad-portfolio → Settings → Deploy keys, WRITE access)
#   bash setup.sh install   # clones, builds the venv, installs the unit and the nginx location
#
# Idempotent: re-running `install` pulls and restarts.
set -euo pipefail

APP_USER=ggadmin
APP_HOME=/var/lib/ggadmin
APP_DIR=/opt/ggmilad-admin
WEBROOT=/var/www/ggmilad
REPO=git@github.com:miladdhq/ggmilad-portfolio.git
VHOST=/etc/nginx/sites-available/ggmilad
UNIT=ggmilad-admin

phase="${1:-}"

ensure_user() {
  id -u "$APP_USER" >/dev/null 2>&1 || useradd -r -m -d "$APP_HOME" -s /usr/sbin/nologin "$APP_USER"
  install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$APP_HOME/.ssh"
}

case "$phase" in
  key)
    ensure_user
    if [ ! -f "$APP_HOME/.ssh/id_ed25519" ]; then
      sudo -u "$APP_USER" ssh-keygen -t ed25519 -N "" -C "ggmilad-admin@ggon.top" -f "$APP_HOME/.ssh/id_ed25519" >/dev/null
    fi
    ssh-keyscan -t ed25519 github.com 2>/dev/null > "$APP_HOME/.ssh/known_hosts"
    chown "$APP_USER:$APP_USER" "$APP_HOME/.ssh/known_hosts"
    echo "Deploy key (add with WRITE access):"
    cat "$APP_HOME/.ssh/id_ed25519.pub"
    ;;

  install)
    ensure_user
    if [ ! -d "$APP_DIR/.git" ]; then
      install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
      sudo -u "$APP_USER" git clone -q "$REPO" "$APP_DIR"
    else
      sudo -u "$APP_USER" git -C "$APP_DIR" pull -q --ff-only
    fi
    sudo -u "$APP_USER" git -C "$APP_DIR" config user.name "GGmilad Admin"
    sudo -u "$APP_USER" git -C "$APP_DIR" config user.email "admin@ggon.top"

    [ -d "$APP_DIR/.venv" ] || sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
    install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/data"

    if [ ! -f "$APP_DIR/.env" ]; then
      cat > "$APP_DIR/.env" <<EOF
ADMIN_PASSWORD_HASH=CHANGE_ME
SESSION_SECRET=$(openssl rand -hex 32)
GG_GIT_SYNC=1
EOF
      chown "$APP_USER:$APP_USER" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"
      echo "!! .env created with a placeholder hash. Run:"
      echo "   sudo -u $APP_USER $APP_DIR/.venv/bin/python -m admin.mkpass   (from $APP_DIR)"
      echo "   and put the hash into $APP_DIR/.env, then: systemctl restart $UNIT"
    fi

    # the panel must be able to replace the live file; nginx must still read it
    chown -R "$APP_USER:www-data" "$WEBROOT"
    chmod 775 "$WEBROOT"
    [ -f "$WEBROOT/index.html" ] && chmod 664 "$WEBROOT/index.html"

    install -m 644 "$APP_DIR/deploy/$UNIT.service" "/etc/systemd/system/$UNIT.service"
    systemctl daemon-reload
    systemctl enable -q "$UNIT"
    systemctl restart "$UNIT"

    if ! grep -q "location /admin/" "$VHOST"; then
      cp -a "$VHOST" "$VHOST.bak.$(date +%F)"
      # insert the snippet right before the `location / {` of the :443 block
      awk -v snippet="$APP_DIR/deploy/nginx-admin.location" '
        /listen 443/ {in443=1}
        in443 && /^    location \/ \{/ && !done { while ((getline line < snippet) > 0) print line; print ""; done=1 }
        {print}
      ' "$VHOST" > "$VHOST.new" && mv "$VHOST.new" "$VHOST"
    fi
    nginx -t
    systemctl reload nginx
    sleep 2
    systemctl --no-pager --lines=5 status "$UNIT" || true
    echo "done: https://ggon.top/admin/"
    ;;

  *)
    echo "usage: $0 key | install" >&2; exit 2 ;;
esac
