from datetime import datetime, timezone
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from awg_client import ConnMode


# ------------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------------

def fmt_bytes(n: int | None) -> str:
    if n is None:
        return "—"
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ПБ"


def fmt_handshake(ts: str | None) -> str:
    if not ts:
        return "никогда"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return f"{diff} сек назад"
        elif diff < 3600:
            return f"{diff // 60} мин назад"
        elif diff < 86400:
            return f"{diff // 3600} ч назад"
        else:
            return f"{diff // 86400} д назад"
    except Exception:
        return ts


def status_emoji(status: str) -> str:
    return {
        "running":  "🟢",
        "stopped":  "🔴",
        "error":    "🔴",
        "starting": "🟡",
        "stopping": "🟡",
    }.get(status, "⚪")


def fmt_tunnel(t: dict) -> str:
    status   = t.get("status", "unknown")
    emoji    = status_emoji(status)
    name     = t.get("name", t.get("id", "?"))
    tid      = t.get("id", "")
    endpoint = t.get("endpoint", "—")
    address  = t.get("address", "—")
    rx       = fmt_bytes(t.get("rxBytes"))
    tx       = fmt_bytes(t.get("txBytes"))
    handshake = fmt_handshake(t.get("lastHandshake"))
    enabled  = "✅ автозапуск вкл" if t.get("enabled") else "⛔ автозапуск выкл"
    backend  = t.get("backendType") or t.get("backend") or "—"

    pc = t.get("pingCheck", {})
    pingcheck_line = ""
    if pc:
        pc_status = pc.get("status", "?")
        pc_emoji = "🟢" if pc_status == "alive" else ("🔴" if pc_status == "dead" else "⚪")
        pingcheck_line = f"\n🔔 Ping-check: {pc_emoji} {pc_status}"

    return (
        f"{emoji} <b>{name}</b> (<code>{tid}</code>)\n"
        f"  Статус: <b>{status}</b>\n"
        f"  {enabled}\n"
        f"  Endpoint: <code>{endpoint}</code>\n"
        f"  Адрес: <code>{address}</code>\n"
        f"  Backend: {backend}\n"
        f"  ↓ {rx} / ↑ {tx}\n"
        f"  Handshake: {handshake}"
        f"{pingcheck_line}"
    )


def fmt_wan(data: dict) -> str:
    ifaces  = data.get("interfaces", {})
    any_up  = data.get("anyWANUp", False)
    lines   = [f"<b>WAN статус</b> {'🌐 есть интернет' if any_up else '❌ нет интернета'}\n"]
    for name, info in ifaces.items():
        up    = info.get("up", False)
        label = info.get("label", name)
        lines.append(f"  {'🟢' if up else '🔴'} {label} (<code>{name}</code>)")
    return "\n".join(lines)


def fmt_conn_mode(mode: ConnMode, last_used: str, has_fallback: bool) -> str:
    mode_labels = {
        ConnMode.AUTO:     "🔀 Авто (основной → запасной)",
        ConnMode.PRIMARY:  "🔒 Только основной (туннель)",
        ConnMode.FALLBACK: "🔓 Только запасной (прямой IP)",
    }
    used_label = "основной 🔒" if last_used == "primary" else "запасной 🔓"
    text = (
        f"<b>🔌 Подключение к AWG Manager</b>\n\n"
        f"Режим: <b>{mode_labels[mode]}</b>\n"
        f"Последний запрос прошёл через: <b>{used_label}</b>\n"
    )
    if not has_fallback:
        text += "\n⚠️ Запасной URL не настроен (<code>AWG_FALLBACK_URL</code> в .env)"
    return text


# ------------------------------------------------------------------
# Keyboards
# ------------------------------------------------------------------

def main_menu_kb(mode: ConnMode | None = None, has_fallback: bool = True) -> InlineKeyboardMarkup:
    # Иконка текущего режима рядом с кнопкой подключения
    conn_icons = {
        ConnMode.AUTO:     "🔀",
        ConnMode.PRIMARY:  "🔒",
        ConnMode.FALLBACK: "🔓",
    }
    conn_icon = conn_icons.get(mode, "🔌") if mode else "🔌"

    rows = [
        [InlineKeyboardButton(text="📊 Статус туннеля", callback_data="status")],
        [
            InlineKeyboardButton(text="▶️ Старт",   callback_data="action:start"),
            InlineKeyboardButton(text="⏹ Стоп",     callback_data="action:stop"),
            InlineKeyboardButton(text="🔄 Рестарт", callback_data="action:restart"),
        ],
        [InlineKeyboardButton(text="🔁 Автозапуск вкл/выкл", callback_data="action:toggle")],
        [
            InlineKeyboardButton(text="🌐 WAN",        callback_data="wan"),
            InlineKeyboardButton(text="🔍 Проверить IP", callback_data="testip"),
        ],
        [InlineKeyboardButton(text="📡 Связность", callback_data="connectivity")],
        [InlineKeyboardButton(text="📋 Логи",      callback_data="logs")],
        [InlineKeyboardButton(text="ℹ️ Система",   callback_data="sysinfo")],
        [InlineKeyboardButton(
            text=f"{conn_icon} Подключение к API",
            callback_data="conn_menu",
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def conn_menu_kb(mode: ConnMode, has_fallback: bool) -> InlineKeyboardMarkup:
    """Меню управления режимом подключения."""
    def mark(m: ConnMode) -> str:
        return "✅ " if mode == m else "    "

    rows = [
        [InlineKeyboardButton(
            text=f"🔍 Проверить оба адреса",
            callback_data="conn_probe",
        )],
        [InlineKeyboardButton(
            text=f"{mark(ConnMode.AUTO)}🔀 Авто (основной → запасной)",
            callback_data="conn_set:auto",
        )],
        [InlineKeyboardButton(
            text=f"{mark(ConnMode.PRIMARY)}🔒 Только основной (туннель)",
            callback_data="conn_set:primary",
        )],
    ]
    if has_fallback:
        rows.append([InlineKeyboardButton(
            text=f"{mark(ConnMode.FALLBACK)}🔓 Только запасной (прямой IP)",
            callback_data="conn_set:fallback",
        )])
    rows.append([InlineKeyboardButton(text="◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


def confirm_kb(action: str, tunnel_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да",  callback_data=f"confirm:{action}:{tunnel_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="menu"),
        ]
    ])
