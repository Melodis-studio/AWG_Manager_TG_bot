#!/bin/sh
# =============================================================================
#  AWG Manager Bot — установка туннеля на роутер Keenetic
#  https://github.com/Melodis-studio/AWG_Manager_TG_bot
# =============================================================================

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { printf "${GREEN}✓${NC} %s\n" "$*"; }
info() { printf "${CYAN}→${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${NC}  %s\n" "$*"; }
err()  { printf "${RED}✗ ОШИБКА:${NC} %s\n" "$*"; exit 1; }
hr()   { printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

FRP_DIR="/opt/etc/frp"
FRP_VERSION="0.61.1"
VPS_IP="45.8.145.62"
VPS_PORT="47382"
AWG_REMOTE_PORT="52819"
INIT_SCRIPT="/opt/etc/init.d/S99frpc"
PIDFILE="/opt/var/run/frpc.pid"
LOGFILE="/opt/var/log/frpc.log"

clear
hr
printf "${BOLD}   AWG Manager Bot — Настройка роутера${NC}\n"
hr
echo ""
printf "  Этот скрипт подключит роутер к твоему VPS.\n"
printf "  Нужно ввести только один токен.\n"
echo ""

# Проверяем Entware
command -v opkg >/dev/null 2>&1 || err "Entware не найден. Установи Entware на роутер через OPKG."

# Если уже установлено и работает
if [ -f "$FRP_DIR/frpc" ] && [ -f "$INIT_SCRIPT" ]; then
  hr
  printf "${BOLD}   Туннель уже установлен${NC}\n"; hr
  echo ""
  printf "  Что сделать?\n\n"
  printf "  1) Перезапустить туннель\n"
  printf "  2) Переустановить с новым токеном\n"
  printf "  3) Выйти\n\n"
  printf "  Выбор [1]: "; read -r CH; CH="${CH:-1}"
  case "$CH" in
    1)
      $INIT_SCRIPT stop 2>/dev/null; sleep 1
      $INIT_SCRIPT start
      sleep 2
      if pgrep frpc >/dev/null 2>&1; then
        printf "${GREEN}✓ Туннель перезапущен${NC}\n"
      else
        printf "${RED}✗ Не удалось запустить. Проверь: cat %s${NC}\n" "$LOGFILE"
      fi
      exit 0 ;;
    3) exit 0 ;;
  esac
fi

# ── Определяем архитектуру ────────────────────────────────────────
hr
printf "${BOLD}   Шаг 1 — Загрузка компонентов${NC}\n"; hr
echo ""
info "Определяю тип процессора роутера..."
ARCH_RAW=$(uname -m)
case "$ARCH_RAW" in
  mips*)   FRP_ARCH="mipsle" ;;
  aarch64) FRP_ARCH="arm64"  ;;
  arm*)    FRP_ARCH="arm"    ;;
  *)       FRP_ARCH="mipsle" ;;
esac
ok "Процессор: $ARCH_RAW"

# ── Скачиваем frpc ────────────────────────────────────────────────
info "Скачиваю frp (это может занять минуту)..."
mkdir -p "$FRP_DIR"
FRP_FILE="frp_${FRP_VERSION}_linux_${FRP_ARCH}"
cd /tmp

# Пробуем основной источник, затем зеркало
wget -q "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${FRP_FILE}.tar.gz" \
  -O frp.tar.gz 2>/dev/null \
|| wget -q "https://ghproxy.com/https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${FRP_FILE}.tar.gz" \
  -O frp.tar.gz 2>/dev/null \
|| err "Не удалось скачать. Проверь интернет на роутере: ping 8.8.8.8"

tar xzf frp.tar.gz 2>/dev/null
cp "${FRP_FILE}/frpc" "$FRP_DIR/" 2>/dev/null || err "Ошибка распаковки архива"
chmod +x "$FRP_DIR/frpc"
rm -rf frp.tar.gz "$FRP_FILE"
ok "Компонент туннеля загружен"

# ── Токен ─────────────────────────────────────────────────────────
hr
printf "${BOLD}   Шаг 2 — Введи токен${NC}\n"; hr
echo ""
printf "  Токен — это секретный ключ для связи роутера с VPS.\n"
printf "  Ты получил его в конце установки на VPS.\n"
echo ""
printf "  Если не помнишь токен:\n"
printf "   • Зайди на VPS по SSH\n"
printf "   • Введи команду: awgbot\n"
printf "   • Выбери пункт 8 (Показать токен)\n"
echo ""
printf "  Вставь токен: "; read -r TOKEN
while [ -z "$TOKEN" ]; do
  warn "Токен не может быть пустым"
  printf "  Вставь токен: "; read -r TOKEN
done
ok "Токен принят"

# ── Конфиг ────────────────────────────────────────────────────────
hr
printf "${BOLD}   Шаг 3 — Настройка подключения${NC}\n"; hr
echo ""
info "Записываю конфигурацию..."

cat > "$FRP_DIR/frpc.toml" << EOF
serverAddr  = "${VPS_IP}"
serverPort  = ${VPS_PORT}
auth.method = "token"
auth.token  = "${TOKEN}"
log.level   = "warn"
log.maxDays = 3

[[proxies]]
name       = "awg-manager"
type       = "tcp"
localIP    = "127.0.0.1"
localPort  = 2222
remotePort = ${AWG_REMOTE_PORT}
EOF
ok "Конфигурация сохранена"

# ── Автозапуск ────────────────────────────────────────────────────
info "Настраиваю автозапуск при перезагрузке роутера..."
mkdir -p /opt/var/run /opt/var/log

cat > "$INIT_SCRIPT" << EOF
#!/bin/sh
PIDFILE="${PIDFILE}"
FRPC="${FRP_DIR}/frpc"
CONF="${FRP_DIR}/frpc.toml"

case "\$1" in
  start)
    echo "Starting frpc tunnel..."
    \$FRPC -c \$CONF > ${LOGFILE} 2>&1 &
    echo \$! > \$PIDFILE
    ;;
  stop)
    echo "Stopping frpc tunnel..."
    [ -f \$PIDFILE ] && kill \$(cat \$PIDFILE) 2>/dev/null
    rm -f \$PIDFILE
    ;;
  restart)
    \$0 stop; sleep 1; \$0 start
    ;;
  status)
    if pgrep frpc >/dev/null 2>&1; then
      echo "Туннель: работает ✓"
    else
      echo "Туннель: остановлен ✗"
    fi
    ;;
  *)
    echo "Использование: \$0 {start|stop|restart|status}"
    ;;
esac
EOF
chmod +x "$INIT_SCRIPT"
ok "Автозапуск настроен"

# ── Запуск ────────────────────────────────────────────────────────
hr
printf "${BOLD}   Шаг 4 — Запуск туннеля${NC}\n"; hr
echo ""
info "Запускаю туннель..."
$INIT_SCRIPT start
sleep 4

if pgrep frpc >/dev/null 2>&1; then
  ok "Туннель запущен успешно!"
else
  err "Туннель не запустился. Проверь лог: cat $LOGFILE"
fi

# ── Финал ─────────────────────────────────────────────────────────
clear; hr
printf "${BOLD}${GREEN}   ✓ Роутер настроен!${NC}\n"; hr
echo ""
printf "  Туннель между роутером и VPS активен.\n"
printf "  Теперь бот в Telegram может управлять твоим роутером.\n"
echo ""
hr
printf "${BOLD}   Что делать дальше:${NC}\n"; hr
echo ""
printf "  1. Открой Telegram\n"
printf "  2. Найди своего бота\n"
printf "  3. Напиши ему: /start\n"
printf "  4. Должно появиться меню управления\n"
echo ""
hr
printf "${BOLD}   Полезные команды для роутера:${NC}\n"; hr
echo ""
printf "  Статус туннеля:    /opt/etc/init.d/S99frpc status\n"
printf "  Перезапустить:     /opt/etc/init.d/S99frpc restart\n"
printf "  Посмотреть лог:    cat /opt/var/log/frpc.log\n"
echo ""
hr
echo ""
