import logging

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from awg_client import AWGClient, ConnMode
from config import Config
from helpers import (
    fmt_tunnel, fmt_wan, fmt_conn_mode,
    main_menu_kb, back_kb, confirm_kb, conn_menu_kb,
    status_emoji,
)

router = Router()
logger = logging.getLogger(__name__)

# Один клиент на всё время работы бота
_client: AWGClient | None = None


def get_client(config: Config) -> AWGClient:
    global _client
    if _client is None:
        _client = AWGClient(
            primary_url=config.AWG_BASE_URL,
            login=config.AWG_LOGIN,
            password=config.AWG_PASSWORD,
            fallback_url=config.AWG_FALLBACK_URL,
        )
    return _client


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def is_allowed(user_id: int, config: Config) -> bool:
    return user_id in config.ALLOWED_USER_IDS


async def get_tunnel_id(client: AWGClient, config: Config) -> tuple[str | None, str]:
    if config.TUNNEL_ID:
        return config.TUNNEL_ID, ""
    result = await client.get_tunnels()
    if not result.get("success"):
        return None, result.get("error", "Ошибка получения туннелей")
    tunnels = result.get("data") or []
    if not tunnels:
        return None, "Туннели не найдены"
    return tunnels[0].get("id", ""), ""


def menu_text(client: AWGClient) -> str:
    mode_label = {
        ConnMode.AUTO:     "🔀 Авто",
        ConnMode.PRIMARY:  "🔒 Туннель",
        ConnMode.FALLBACK: "🔓 Прямой IP",
    }.get(client.mode, "?")
    return f"📋 <b>Главное меню</b>\n<i>Подключение: {mode_label}</i>"


# ------------------------------------------------------------------
# /start, /menu
# ------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, config: Config):
    if not is_allowed(message.from_user.id, config):
        await message.answer("⛔ Нет доступа.")
        return
    client = get_client(config)
    await message.answer(
        menu_text(client),
        reply_markup=main_menu_kb(client.mode, client.has_fallback),
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, config: Config):
    if not is_allowed(message.from_user.id, config):
        return
    client = get_client(config)
    await message.answer(
        menu_text(client),
        reply_markup=main_menu_kb(client.mode, client.has_fallback),
        parse_mode="HTML",
    )


# ------------------------------------------------------------------
# Callback: меню
# ------------------------------------------------------------------

@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    client = get_client(config)
    await call.message.edit_text(
        menu_text(client),
        reply_markup=main_menu_kb(client.mode, client.has_fallback),
        parse_mode="HTML",
    )
    await call.answer()


# ------------------------------------------------------------------
# Callback: статус туннеля
# ------------------------------------------------------------------

@router.callback_query(F.data == "status")
async def cb_status(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return

    await call.answer("⏳ Запрашиваю...")
    client = get_client(config)
    result = await client.get_tunnels()

    if not result.get("success"):
        text = f"❌ Ошибка: {result.get('error', '?')}"
    else:
        tunnels = result.get("data") or []
        text = "\n\n".join(fmt_tunnel(t) for t in tunnels) if tunnels else "ℹ️ Туннелей нет"

    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# ------------------------------------------------------------------
# Callback: действия (start/stop/restart/toggle)
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("action:"))
async def cb_action(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return

    action = call.data.split(":")[1]
    client = get_client(config)
    tunnel_id, err = await get_tunnel_id(client, config)
    if err:
        await call.message.edit_text(f"❌ {err}", reply_markup=back_kb())
        await call.answer(); return

    if action == "stop":
        await call.message.edit_text(
            "⚠️ <b>Остановить туннель?</b>\n\nПодтверди действие.",
            reply_markup=confirm_kb("stop", tunnel_id),
            parse_mode="HTML",
        )
        await call.answer(); return

    await call.answer("⏳")
    await _run_action(call, client, action, tunnel_id)


@router.callback_query(F.data.startswith("confirm:"))
async def cb_confirm(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    _, action, tunnel_id = call.data.split(":", 2)
    client = get_client(config)
    await call.answer("⏳")
    await _run_action(call, client, action, tunnel_id)


async def _run_action(call: CallbackQuery, client: AWGClient, action: str, tunnel_id: str):
    fn_map = {
        "start":   client.start_tunnel,
        "stop":    client.stop_tunnel,
        "restart": client.restart_tunnel,
        "toggle":  client.toggle_enabled,
    }
    labels = {
        "start":   "▶️ Запуск",
        "stop":    "⏹ Остановка",
        "restart": "🔄 Рестарт",
        "toggle":  "🔁 Переключение автозапуска",
    }
    fn = fn_map.get(action)
    if not fn:
        await call.message.edit_text("❓ Неизвестное действие", reply_markup=back_kb()); return

    result = await fn(tunnel_id)
    if not result.get("success"):
        text = f"❌ Ошибка: {result.get('error', '?')}"
    else:
        t       = result.get("data") or {}
        status  = t.get("status", "?")
        emoji   = status_emoji(status)
        name    = t.get("name", tunnel_id)
        enabled = t.get("enabled", False)
        text = (
            f"✅ <b>{labels[action]}</b>\n\n"
            f"{emoji} <b>{name}</b>\n"
            f"Статус: <b>{status}</b>\n"
            f"Автозапуск: {'✅' if enabled else '⛔'}"
        )
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# ------------------------------------------------------------------
# Callback: WAN
# ------------------------------------------------------------------

@router.callback_query(F.data == "wan")
async def cb_wan(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    await call.answer("⏳")
    client = get_client(config)
    result = await client.get_wan_status()
    text = fmt_wan(result.get("data") or result) if result.get("success") else f"❌ {result.get('error', '?')}"
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# ------------------------------------------------------------------
# Callback: проверить IP
# ------------------------------------------------------------------

@router.callback_query(F.data == "testip")
async def cb_testip(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    await call.answer("⏳ Проверяю IP...")
    client = get_client(config)
    tunnel_id, err = await get_tunnel_id(client, config)
    if err:
        await call.message.edit_text(f"❌ {err}", reply_markup=back_kb()); return

    result = await client.test_ip(tunnel_id)
    if not result.get("success"):
        text = f"❌ {result.get('error', '?')}"
    else:
        data    = result.get("data") or {}
        ip      = data.get("ip", "?")
        service = data.get("service", "")
        text = f"🌐 <b>Внешний IP через туннель</b>\n\n<code>{ip}</code>\n\nСервис: {service}"
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# ------------------------------------------------------------------
# Callback: связность
# ------------------------------------------------------------------

@router.callback_query(F.data == "connectivity")
async def cb_connectivity(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    await call.answer("⏳ Проверяю...")
    client = get_client(config)
    tunnel_id, err = await get_tunnel_id(client, config)
    if err:
        await call.message.edit_text(f"❌ {err}", reply_markup=back_kb()); return

    result = await client.test_connectivity(tunnel_id)
    if not result.get("success"):
        text = f"❌ {result.get('error', '?')}"
    else:
        data      = result.get("data") or {}
        connected = data.get("connected", False)
        latency   = data.get("latency")
        reason    = data.get("reason", "")
        if connected:
            text = f"📡 <b>Туннель работает</b>\n\n✅ Связность есть\nЗадержка: <b>{latency} мс</b>"
        else:
            text = f"📡 <b>Проблема с туннелем</b>\n\n❌ Нет связности\nПричина: {reason or '?'}"
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# ------------------------------------------------------------------
# Callback: логи
# ------------------------------------------------------------------

@router.callback_query(F.data == "logs")
async def cb_logs(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    await call.answer("⏳")
    client = get_client(config)
    result = await client.get_logs(limit=15)

    if not result.get("success"):
        text = f"❌ {result.get('error', '?')}"
    else:
        data = result.get("data") or {}
        logs = data.get("logs") or []
        if not logs:
            text = "📋 Логов нет"
        else:
            lvl_icons = {"INFO": "ℹ️", "WARN": "⚠️", "ERROR": "🔴", "DEBUG": "🔵"}
            lines = []
            for entry in logs[-15:]:
                level = entry.get("level", "info").upper()
                msg   = entry.get("message", "")
                ts    = entry.get("timestamp", "")[:16].replace("T", " ")
                icon  = lvl_icons.get(level, "•")
                lines.append(f"{icon} <code>{ts}</code> {msg}")
            text = "<b>📋 Последние логи туннеля</b>\n\n" + "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# ------------------------------------------------------------------
# Callback: системная инфо
# ------------------------------------------------------------------

@router.callback_query(F.data == "sysinfo")
async def cb_sysinfo(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    await call.answer("⏳")
    client = get_client(config)
    result = await client.get_system_info()

    if not result.get("success"):
        text = f"❌ {result.get('error', '?')}"
    else:
        d          = result.get("data") or {}
        version    = d.get("version", "?")
        os_ver     = d.get("keeneticOS", "?")
        arch       = d.get("goArch", "?")
        backend    = d.get("activeBackend", "?")
        ram_mb     = d.get("totalMemoryMB")
        low_mem    = d.get("isLowMemory", False)
        mod_loaded = d.get("kernelModuleLoaded", False)
        singbox    = d.get("singbox", {})
        sb_ver     = singbox.get("version", "не установлен") if singbox.get("installed") else "не установлен"
        ram_line   = f"{ram_mb} МБ {'⚠️ мало' if low_mem else ''}" if ram_mb else "?"
        text = (
            f"ℹ️ <b>Системная информация</b>\n\n"
            f"AWG Manager: <b>{version}</b>\n"
            f"Keenetic OS: <b>{os_ver}</b>\n"
            f"Архитектура: <code>{arch}</code>\n"
            f"Бэкенд: <b>{backend}</b>\n"
            f"Ядро: {'✅ загружено' if mod_loaded else '❌ не загружено'}\n"
            f"RAM: {ram_line}\n"
            f"Sing-box: {sb_ver}"
        )
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")


# ==================================================================
# БЛОК: управление подключением к API
# ==================================================================

@router.callback_query(F.data == "conn_menu")
async def cb_conn_menu(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    client = get_client(config)
    text = fmt_conn_mode(client.mode, client.last_mode_used, client.has_fallback)
    await call.message.edit_text(
        text,
        reply_markup=conn_menu_kb(client.mode, client.has_fallback),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("conn_set:"))
async def cb_conn_set(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return

    mode_str = call.data.split(":")[1]
    mode_map = {"auto": ConnMode.AUTO, "primary": ConnMode.PRIMARY, "fallback": ConnMode.FALLBACK}
    new_mode = mode_map.get(mode_str)
    if not new_mode:
        await call.answer("❓ Неизвестный режим", show_alert=True); return

    client = get_client(config)

    if new_mode == ConnMode.FALLBACK and not client.has_fallback:
        await call.answer("⚠️ AWG_FALLBACK_URL не задан в .env", show_alert=True); return

    client.set_mode(new_mode)

    labels = {
        ConnMode.AUTO:     "🔀 Авто",
        ConnMode.PRIMARY:  "🔒 Только туннель",
        ConnMode.FALLBACK: "🔓 Только прямой IP",
    }
    await call.answer(f"✅ Режим: {labels[new_mode]}")

    text = fmt_conn_mode(client.mode, client.last_mode_used, client.has_fallback)
    await call.message.edit_text(
        text,
        reply_markup=conn_menu_kb(client.mode, client.has_fallback),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "conn_probe")
async def cb_conn_probe(call: CallbackQuery, config: Config):
    if not is_allowed(call.from_user.id, config):
        await call.answer("⛔", show_alert=True); return
    await call.answer("⏳ Проверяю адреса...")

    client  = get_client(config)
    results = await client.probe_urls()

    primary_ok  = results.get("primary", False)
    fallback_ok = results.get("fallback")

    primary_url  = config.AWG_BASE_URL
    fallback_url = config.AWG_FALLBACK_URL or "не задан"

    lines = [
        "<b>🔍 Проверка адресов AWG Manager</b>\n",
        f"{'🟢' if primary_ok else '🔴'} <b>Основной</b> (туннель)\n   <code>{primary_url}</code>",
    ]
    if config.AWG_FALLBACK_URL:
        fb_icon = '🟢' if fallback_ok else '🔴'
        lines.append(f"{fb_icon} <b>Запасной</b> (прямой IP)\n   <code>{fallback_url}</code>")
    else:
        lines.append(f"⚪ <b>Запасной</b> — не настроен\n   Добавь <code>AWG_FALLBACK_URL</code> в .env")

    # Рекомендация
    lines.append("")
    if primary_ok:
        lines.append("💡 Рекомендуется режим: <b>🔒 Только туннель</b> или <b>🔀 Авто</b>")
    elif fallback_ok:
        lines.append("💡 Туннель недоступен. Переключись на <b>🔓 Прямой IP</b>")
    else:
        lines.append("❌ Оба адреса недоступны. Проверь роутер и настройки.")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=conn_menu_kb(client.mode, client.has_fallback),
        parse_mode="HTML",
    )
