#!/bin/bash
# =============================================================================
#  AWG Manager Telegram Bot — установка на VPS
#  https://github.com/Melodis-studio/AWG_Manager_TG_bot
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}→${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗ ОШИБКА:${NC} $*"; exit 1; }
hr()   { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
pause(){ read -rp "  Нажми Enter чтобы продолжить..." _; }

REPO="https://raw.githubusercontent.com/Melodis-studio/AWG_Manager_TG_bot/main"
INSTALL_DIR="/opt/awg_bot"
VENV_DIR="$INSTALL_DIR/venv"
FRP_DIR="/opt/frp"
FRP_VERSION="0.61.1"
BOT_USER="awgbot"
SERVICE="awg-bot"
CMD="/usr/local/bin/awgbot"

clear
hr
echo -e "${BOLD}   AWG Manager Telegram Bot — Установка${NC}"
hr
echo ""
echo -e "  Этот скрипт автоматически установит и настроит бота."
echo -e "  Тебе нужно будет ввести всего 4 значения."
echo ""
pause

[[ $EUID -ne 0 ]] && err "Запусти от root (sudo -i)"

# ── Режим установки ────────────────────────────────────────────────
IS_UPDATE=false
if [[ -f "$INSTALL_DIR/bot.py" ]]; then
  IS_UPDATE=true
  clear; hr
  echo -e "${BOLD}   Обнаружена существующая установка${NC}"; hr
  echo ""
  echo "  1) Обновить бота (настройки сохранятся)"
  echo "  2) Установить заново (все настройки будут запрошены снова)"
  echo "  3) Выйти"
  echo ""
  read -rp "  Выбор [1]: " CH; CH="${CH:-1}"
  case "$CH" in
    2) IS_UPDATE=false ;;
    3) exit 0 ;;
  esac
fi

# ── Шаг 1: системные пакеты ───────────────────────────────────────
clear; hr
echo -e "${BOLD}   Шаг 1 из 5 — Подготовка системы${NC}"; hr
echo ""
info "Устанавливаю необходимые пакеты..."
echo ""
apt-get update -qq
for pkg in python3 python3-venv python3-pip curl wget; do
  dpkg -s "$pkg" &>/dev/null || apt-get install -y -qq "$pkg"
done
ok "Система подготовлена"

# ── Шаг 2: файлы бота ─────────────────────────────────────────────
clear; hr
echo -e "${BOLD}   Шаг 2 из 5 — Загрузка файлов бота${NC}"; hr
echo ""
info "Скачиваю файлы с GitHub..."
echo ""
mkdir -p "$INSTALL_DIR"
for f in bot.py config.py awg_client.py handlers.py helpers.py requirements.txt; do
  curl -fsSL "$REPO/$f" -o "$INSTALL_DIR/$f" \
    && ok "  $f" \
    || err "Не удалось скачать $f. Проверь интернет-соединение."
done
echo ""
info "Устанавливаю Python-зависимости..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
ok "Файлы и зависимости готовы"

# ── Шаг 3: frp туннель ────────────────────────────────────────────
clear; hr
echo -e "${BOLD}   Шаг 3 из 5 — Настройка туннеля до роутера${NC}"; hr
echo ""
echo -e "  Так как у большинства домашних провайдеров 'серый' IP,"
echo -e "  бот подключается к роутеру через защищённый туннель."
echo -e "  Это происходит автоматически — ничего настраивать не нужно."
echo ""
info "Устанавливаю frp..."

if [[ ! -f "$FRP_DIR/frps" ]]; then
  ARCH=$(uname -m)
  [[ "$ARCH" == "aarch64" ]] && FA="arm64" || FA="amd64"
  cd /tmp
  wget -q "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${FA}.tar.gz" \
    -O frp.tar.gz 2>/dev/null || \
  err "Не удалось скачать frp. Проверь интернет."
  tar xzf frp.tar.gz
  mkdir -p "$FRP_DIR"
  cp "frp_${FRP_VERSION}_linux_${FA}/frps" "$FRP_DIR/"
  chmod +x "$FRP_DIR/frps"
  rm -rf frp.tar.gz "frp_${FRP_VERSION}_linux_${FA}"
fi

# Генерируем токен
if [[ ! -f "$FRP_DIR/.token" ]]; then
  TOKEN=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)
  printf '%s' "$TOKEN" > "$FRP_DIR/.token"
  chmod 600 "$FRP_DIR/.token"
else
  TOKEN=$(cat "$FRP_DIR/.token")
fi

cat > "$FRP_DIR/frps.toml" << EOF
bindPort    = 47382
auth.method = "token"
auth.token  = "${TOKEN}"
log.level   = "warn"
EOF

cat > /etc/systemd/system/frps.service << EOF
[Unit]
Description=frp Server (AWG tunnel)
After=network.target
[Service]
Type=simple
ExecStart=${FRP_DIR}/frps -c ${FRP_DIR}/frps.toml
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable frps --quiet
systemctl restart frps
sleep 1
systemctl is-active --quiet frps \
  && ok "Туннельный сервер запущен" \
  || warn "Туннельный сервер не запустился — попробуй переустановить"

# ── Шаг 4: настройки пользователя ─────────────────────────────────
if [[ "$IS_UPDATE" == "false" ]]; then
  clear; hr
  echo -e "${BOLD}   Шаг 4 из 5 — Твои данные для настройки бота${NC}"; hr
  echo ""
  echo -e "  Нужно ввести 4 значения. Подсказка по каждому — прямо под вопросом."
  echo ""

  # ── BOT_TOKEN ──────────────────────────────────────────────────
  hr
  echo -e "${BOLD}  1/4 — Токен Telegram-бота${NC}"
  echo ""
  echo -e "  Как получить:"
  echo -e "   • Открой Telegram"
  echo -e "   • Найди бота ${BOLD}@BotFather${NC}"
  echo -e "   • Напиши ему /newbot"
  echo -e "   • Придумай имя боту (например: Мой роутер)"
  echo -e "   • Придумай username боту — латиницей, оканчивается на bot"
  echo -e "     (например: myrouter_awg_bot)"
  echo -e "   • BotFather пришлёт токен вида: 1234567890:AAxxxxxxxxxxxxxx"
  echo -e "   • Скопируй и вставь его сюда"
  echo ""
  read -rp "  Вставь токен: " BOT_TOKEN
  while [[ -z "$BOT_TOKEN" || ! "$BOT_TOKEN" =~ ^[0-9]+:.+ ]]; do
    warn "Токен выглядит неверно. Он должен быть вида 1234567890:AAxxxxxxx"
    read -rp "  Вставь токен: " BOT_TOKEN
  done
  ok "Токен принят"

  # ── ALLOWED_USER_IDS ───────────────────────────────────────────
  echo ""
  hr
  echo -e "${BOLD}  2/4 — Твой личный Telegram ID${NC}"
  echo ""
  echo -e "  Это число — твой уникальный номер в Telegram."
  echo -e "  Бот будет отвечать ТОЛЬКО тебе — это защита от чужих."
  echo ""
  echo -e "  Как узнать свой ID:"
  echo -e "   • Открой Telegram"
  echo -e "   • Найди бота ${BOLD}@userinfobot${NC}"
  echo -e "   • Напиши ему /start"
  echo -e "   • Он ответит: Id: 123456789"
  echo -e "   • Скопируй и вставь это число сюда"
  echo ""
  read -rp "  Вставь свой ID: " ALLOWED_USER_IDS
  while [[ -z "$ALLOWED_USER_IDS" || ! "$ALLOWED_USER_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]]; do
    warn "ID должен состоять только из цифр (например: 123456789)"
    read -rp "  Вставь свой ID: " ALLOWED_USER_IDS
  done
  ok "ID принят"

  # ── AWG_PASSWORD ───────────────────────────────────────────────
  echo ""
  hr
  echo -e "${BOLD}  3/4 — Пароль от роутера Keenetic${NC}"
  echo ""
  echo -e "  Это пароль который ты вводишь при входе"
  echo -e "  в веб-интерфейс роутера (обычно 192.168.1.1)"
  echo ""
  echo -e "  ${YELLOW}⚠ Пароль не отображается при вводе — это нормально${NC}"
  echo ""
  read -rsp "  Вставь пароль: " AWG_PASSWORD; echo ""
  while [[ -z "$AWG_PASSWORD" ]]; do
    warn "Пароль не может быть пустым"
    read -rsp "  Вставь пароль: " AWG_PASSWORD; echo ""
  done
  ok "Пароль принят"

  # ── TUNNEL_ID ──────────────────────────────────────────────────
  echo ""
  hr
  echo -e "${BOLD}  4/4 — ID твоего туннеля в AWG Manager${NC}"
  echo ""
  echo -e "  Как узнать:"
  echo -e "   • Открой в браузере: ${BOLD}http://192.168.1.1:2222${NC}"
  echo -e "   • Найди свой туннель и нажми кнопку ${BOLD}«Изменить»${NC}"
  echo -e "   • Посмотри на адресную строку браузера"
  echo -e "   • Там будет: .../tunnels/${BOLD}awg10${NC}"
  echo -e "   • Последняя часть после /tunnels/ — это и есть ID"
  echo ""
  echo -e "  Если у тебя стандартная установка — скорее всего ${BOLD}awg10${NC}"
  echo ""
  read -rp "  ID туннеля [awg10]: " TUNNEL_ID
  TUNNEL_ID="${TUNNEL_ID:-awg10}"
  ok "ID туннеля: $TUNNEL_ID"

  # ── Записываем .env ────────────────────────────────────────────
  printf 'BOT_TOKEN=%s\n'           "$BOT_TOKEN"        > "$INSTALL_DIR/.env"
  printf 'ALLOWED_USER_IDS=%s\n'    "$ALLOWED_USER_IDS" >> "$INSTALL_DIR/.env"
  printf 'AWG_BASE_URL=%s\n'        "http://localhost:52819/api" >> "$INSTALL_DIR/.env"
  printf 'AWG_FALLBACK_URL=\n'                          >> "$INSTALL_DIR/.env"
  printf 'AWG_LOGIN=%s\n'           "admin"             >> "$INSTALL_DIR/.env"
  printf 'AWG_PASSWORD=%s\n'        "$AWG_PASSWORD"     >> "$INSTALL_DIR/.env"
  printf 'TUNNEL_ID=%s\n'           "$TUNNEL_ID"        >> "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env"

else
  ok "Настройки сохранены без изменений"
fi

# ── Шаг 5: запуск ─────────────────────────────────────────────────
clear; hr
echo -e "${BOLD}   Шаг 5 из 5 — Запуск бота${NC}"; hr
echo ""

id "$BOT_USER" &>/dev/null || useradd -r -s /bin/false "$BOT_USER"
chown -R "$BOT_USER:$BOT_USER" "$INSTALL_DIR"

cat > "/etc/systemd/system/${SERVICE}.service" << EOF
[Unit]
Description=AWG Manager Telegram Bot
After=network.target

[Service]
Type=simple
User=${BOT_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${VENV_DIR}/bin/python bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE" --quiet
systemctl is-active --quiet "$SERVICE" \
  && systemctl restart "$SERVICE" \
  || systemctl start "$SERVICE"
sleep 2

if systemctl is-active --quiet "$SERVICE"; then
  ok "Бот запущен и работает"
else
  warn "Бот не запустился. Смотри логи: journalctl -u $SERVICE -n 30"
fi

# ── Команда awgbot ─────────────────────────────────────────────────
cat > "$CMD" << 'CMDEOF'
#!/bin/bash
SERVICE="awg-bot"
REPO="https://raw.githubusercontent.com/Melodis-studio/AWG_Manager_TG_bot/main"
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
hr()   { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
pause(){ read -rp "  Нажми Enter для возврата в меню..." _; }

show_menu() {
  clear; hr
  echo -e "${BOLD}   AWG Manager Bot — Панель управления${NC}"; hr

  STATUS=$(systemctl is-active "$SERVICE" 2>/dev/null || echo "inactive")
  FRP_OK=$(systemctl is-active frps 2>/dev/null || echo "inactive")
  API_OK=$(curl -s -m 3 http://localhost:52819/api/health 2>/dev/null | grep -c '"ok":true' || true)

  echo ""
  if [[ "$STATUS" == "active" ]]; then
    echo -e "  🤖 Бот:            ${GREEN}работает ✓${NC}"
  else
    echo -e "  🤖 Бот:            ${RED}остановлен ✗${NC}"
  fi
  if [[ "$FRP_OK" == "active" ]]; then
    echo -e "  🔗 Туннель (VPS):  ${GREEN}работает ✓${NC}"
  else
    echo -e "  🔗 Туннель (VPS):  ${RED}остановлен ✗${NC}"
  fi
  if [[ "$API_OK" == "1" ]]; then
    echo -e "  📡 Связь с роутером: ${GREEN}есть ✓${NC}"
  else
    echo -e "  📡 Связь с роутером: ${RED}нет ✗${NC}"
  fi
  echo ""
  hr
  echo -e "  ${BOLD}Управление ботом:${NC}"
  echo "   1) Перезапустить бота"
  echo "   2) Остановить бота"
  echo "   3) Запустить бота"
  echo "   4) Показать логи (Ctrl+C для выхода)"
  echo ""
  echo -e "  ${BOLD}Настройки:${NC}"
  echo "   5) Изменить настройки бота"
  echo "   6) Обновить бота до последней версии"
  echo ""
  echo -e "  ${BOLD}Диагностика:${NC}"
  echo "   7) Проверить связь с роутером"
  echo "   8) Показать токен для роутера"
  echo ""
  echo -e "  ${BOLD}Удаление:${NC}"
  echo "   9) Полностью удалить бота с VPS"
  echo ""
  echo "   0) Выход"
  echo ""
  read -rp "  Выбор: " CH
  echo ""
  handle "$CH"
}

handle() {
  case "$1" in
    1)
      systemctl restart "$SERVICE" \
        && echo -e "  ${GREEN}✓ Бот перезапущен${NC}" \
        || echo -e "  ${RED}✗ Ошибка перезапуска${NC}"
      sleep 1; show_menu ;;
    2)
      systemctl stop "$SERVICE" \
        && echo -e "  ${GREEN}✓ Бот остановлен${NC}" \
        || echo -e "  ${RED}✗ Ошибка${NC}"
      sleep 1; show_menu ;;
    3)
      systemctl start "$SERVICE" \
        && echo -e "  ${GREEN}✓ Бот запущен${NC}" \
        || echo -e "  ${RED}✗ Ошибка${NC}"
      sleep 1; show_menu ;;
    4)
      echo -e "  ${CYAN}Логи бота (нажми Ctrl+C чтобы выйти):${NC}"
      echo ""
      journalctl -u "$SERVICE" -f --no-pager ;;
    5)
      clear; hr
      echo -e "${BOLD}   Изменение настроек${NC}"; hr
      echo ""
      echo -e "  ${YELLOW}После изменений бот будет перезапущен автоматически${NC}"
      echo ""
      ${EDITOR:-nano} /opt/awg_bot/.env
      systemctl restart "$SERVICE"
      echo -e "  ${GREEN}✓ Настройки сохранены, бот перезапущен${NC}"
      sleep 1; show_menu ;;
    6)
      clear; hr
      echo -e "${BOLD}   Обновление бота${NC}"; hr
      echo ""
      echo -e "  Загружаю новую версию с GitHub..."
      echo ""
      bash <(curl -sL "$REPO/install_vps.sh")  ;;
    7)
      clear; hr
      echo -e "${BOLD}   Проверка связи с роутером${NC}"; hr
      echo ""
      echo -e "  Проверяю туннель..."
      echo ""
      RESULT=$(curl -s -m 5 http://localhost:52819/api/health 2>/dev/null || echo "")
      if echo "$RESULT" | grep -q '"ok":true'; then
        echo -e "  ${GREEN}✓ Связь с роутером есть!${NC}"
        VERSION=$(echo "$RESULT" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
        echo -e "  AWG Manager версия: ${BOLD}$VERSION${NC}"
      else
        echo -e "  ${RED}✗ Роутер не отвечает${NC}"
        echo ""
        echo -e "  Что делать:"
        echo -e "   1. Убедись что роутер включён и подключён к интернету"
        echo -e "   2. Зайди на роутер по SSH:"
        echo -e "      ${BOLD}ssh root@192.168.1.1 -p 222${NC}"
        echo -e "   3. Проверь туннель:"
        echo -e "      ${BOLD}/opt/etc/init.d/S99frpc status${NC}"
        echo -e "   4. Если остановлен — запусти:"
        echo -e "      ${BOLD}/opt/etc/init.d/S99frpc start${NC}"
      fi
      echo ""; pause; show_menu ;;
    8)
      clear; hr
      echo -e "${BOLD}   Токен для роутера${NC}"; hr
      echo ""
      echo -e "  Этот токен нужно ввести при установке скрипта на роутер."
      echo ""
      TOKEN=$(cat /opt/frp/.token 2>/dev/null || echo "файл не найден")
      echo -e "  ${BOLD}${CYAN}${TOKEN}${NC}"
      echo ""
      echo -e "  Команда для роутера (выполнить в SSH-консоли роутера):"
      echo -e "  ${BOLD}curl -sL https://raw.githubusercontent.com/Melodis-studio/AWG_Manager_TG_bot/main/install_router.sh | sh${NC}"
      echo ""; pause; show_menu ;;
    9)
      clear; hr
      echo -e "${BOLD}   Удаление бота с VPS${NC}"; hr
      echo ""
      echo -e "  ${RED}Это удалит бота, все настройки и туннельный сервер.${NC}"
      echo -e "  Данные на роутере не затрагиваются."
      echo ""
      read -rp "  Ты уверен? Введи YES для подтверждения: " CONFIRM
      if [[ "$CONFIRM" == "YES" ]]; then
        echo ""
        echo -e "  Останавливаю сервисы..."
        systemctl stop awg-bot frps 2>/dev/null || true
        systemctl disable awg-bot frps 2>/dev/null || true
        rm -f /etc/systemd/system/awg-bot.service
        rm -f /etc/systemd/system/frps.service
        systemctl daemon-reload
        echo -e "  Удаляю файлы..."
        rm -rf /opt/awg_bot
        rm -rf /opt/frp
        rm -f /usr/local/bin/awgbot
        userdel awgbot 2>/dev/null || true
        echo ""
        echo -e "  ${GREEN}✓ Бот полностью удалён с VPS.${NC}"
        echo ""
        echo -e "  Не забудь удалить туннель на роутере:"
        echo -e "  ${BOLD}ssh root@192.168.1.1 -p 222${NC}"
        echo -e "  Затем: ${BOLD}/opt/etc/init.d/S99frpc stop && rm -rf /opt/etc/frp /opt/etc/init.d/S99frpc${NC}"
        echo ""
        exit 0
      else
        echo -e "  ${YELLOW}Отменено.${NC}"
        sleep 1; show_menu
      fi ;;
    0|"")
      echo "  Выход."; exit 0 ;;
    *)
      show_menu ;;
  esac
}

case "${1:-}" in
  start)   systemctl start   "$SERVICE" ;;
  stop)    systemctl stop    "$SERVICE" ;;
  restart) systemctl restart "$SERVICE" ;;
  logs)    journalctl -u "$SERVICE" -f --no-pager ;;
  status)  systemctl status  "$SERVICE" --no-pager ;;
  update)  bash <(curl -sL "$REPO/install_vps.sh") ;;
  tunnel)    curl -s http://localhost:52819/api/health ;;
  token)     cat /opt/frp/.token ;;
  uninstall) handle 9 ;;
  *)         show_menu ;;
esac
CMDEOF
chmod +x "$CMD"

# ── Итоговый экран ─────────────────────────────────────────────────
clear; hr
echo -e "${BOLD}${GREEN}   ✓ Установка завершена!${NC}"; hr
echo ""
echo -e "  Бот установлен и запущен."
echo ""
echo -e "  ${BOLD}Теперь нужно настроить роутер.${NC}"
echo -e "  Это последний шаг — займёт 2 минуты."
echo ""
hr
echo -e "${BOLD}   Твой токен для роутера:${NC}"
hr
echo ""
echo -e "  ${BOLD}${YELLOW}$(cat "$FRP_DIR/.token")${NC}"
echo ""
echo -e "  ${RED}Скопируй его — он понадобится при установке на роутер!${NC}"
echo ""
hr
echo -e "${BOLD}   Что делать дальше:${NC}"
hr
echo ""
echo -e "  Смотри инструкцию — Шаг 3: Установка на роутер."
echo ""
echo -e "  Управление ботом: введи команду ${BOLD}${CYAN}awgbot${NC}"
echo ""
hr
echo ""
