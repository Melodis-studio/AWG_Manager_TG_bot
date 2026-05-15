import asyncio
import logging
from enum import Enum
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

SESSION_REFRESH_THRESHOLD = 300  # обновлять сессию за 5 мин до истечения


class ConnMode(str, Enum):
    AUTO     = "auto"      # авто-фолбэк: сначала основной, потом запасной
    PRIMARY  = "primary"   # только основной (через туннель)
    FALLBACK = "fallback"  # только запасной (прямой IP)


class AWGClient:
    """
    Клиент AWG Manager API.

    Режимы подключения (ConnMode):
      AUTO     — пробует PRIMARY, при ошибке переключается на FALLBACK
      PRIMARY  — всегда через основной URL (туннель)
      FALLBACK — всегда через запасной URL (прямой IP)

    Текущий активный URL хранится в active_url.
    last_mode_used показывает, каким путём прошёл последний запрос.
    """

    def __init__(self, primary_url: str, login: str, password: str,
                 fallback_url: str | None = None):
        self._primary_url  = primary_url.rstrip("/")
        self._fallback_url = fallback_url.rstrip("/") if fallback_url else None
        self._login    = login
        self._password = password

        self._session: aiohttp.ClientSession | None = None

        # Отдельные cookies для каждого URL
        self._cookies: dict[str, str | None] = {
            self._primary_url: None,
            **(({self._fallback_url: None}) if self._fallback_url else {}),
        }

        # Текущий режим — по умолчанию AUTO
        self.mode: ConnMode = ConnMode.AUTO

        # Какой URL был использован в последнем запросе
        self.last_mode_used: str = "primary"

    # ------------------------------------------------------------------
    # URL selection
    # ------------------------------------------------------------------

    def _urls_to_try(self) -> list[tuple[str, str]]:
        """Возвращает список (url, label) в порядке приоритета для текущего режима."""
        if self.mode == ConnMode.PRIMARY:
            return [(self._primary_url, "primary")]
        if self.mode == ConnMode.FALLBACK:
            if not self._fallback_url:
                return [(self._primary_url, "primary")]
            return [(self._fallback_url, "fallback")]
        # AUTO
        urls = [(self._primary_url, "primary")]
        if self._fallback_url:
            urls.append((self._fallback_url, "fallback"))
        return urls

    @property
    def active_url(self) -> str:
        if self.mode == ConnMode.FALLBACK and self._fallback_url:
            return self._fallback_url
        return self._primary_url

    @property
    def has_fallback(self) -> bool:
        return self._fallback_url is not None

    def set_mode(self, mode: ConnMode):
        self.mode = mode
        # Сбрасываем cookies при смене режима — заставим залогиниться заново
        for k in self._cookies:
            self._cookies[k] = None
        logger.info("AWG: режим подключения изменён на %s", mode.value)

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _ensure_auth(self, base_url: str) -> bool:
        """Проверяет/получает сессию для конкретного base_url."""
        session = await self._get_session()
        cookie = self._cookies.get(base_url)

        if cookie:
            try:
                async with session.get(
                    f"{base_url}/auth/status",
                    headers={"Cookie": f"awg_session={cookie}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("authDisabled") or data.get("expiresIn", 0) > SESSION_REFRESH_THRESHOLD:
                            return True
            except Exception:
                pass

        # Логинимся
        try:
            async with session.post(
                f"{base_url}/auth/login",
                json={"login": self._login, "password": self._password},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    set_cookie = resp.headers.get("Set-Cookie", "")
                    for part in set_cookie.split(";"):
                        part = part.strip()
                        if part.startswith("awg_session="):
                            self._cookies[base_url] = part.split("=", 1)[1]
                            logger.info("AWG [%s]: авторизация успешна", base_url)
                            return True
                    body = await resp.json()
                    if body.get("success"):
                        self._cookies[base_url] = ""  # auth disabled
                        return True
                logger.error("AWG [%s]: login failed status=%s", base_url, resp.status)
                return False
        except Exception as e:
            logger.error("AWG [%s]: login exception: %s", base_url, e)
            return False

    # ------------------------------------------------------------------
    # Low-level request (с фолбэком)
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, _retry: bool = False, **kwargs) -> dict[str, Any]:
        session = await self._get_session()

        for base_url, label in self._urls_to_try():
            if not await self._ensure_auth(base_url):
                continue

            cookie = self._cookies.get(base_url)
            headers = dict(kwargs.pop("headers", {}))
            if cookie:
                headers["Cookie"] = f"awg_session={cookie}"

            url = f"{base_url}{path}"
            try:
                async with session.request(
                    method, url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                    **kwargs,
                ) as resp:
                    try:
                        data = await resp.json()
                    except Exception:
                        text = await resp.text()
                        return {"success": False, "error": f"Неожиданный ответ: {text[:200]}"}

                    if resp.status == 401 and not _retry:
                        self._cookies[base_url] = None
                        return await self._request(method, path, _retry=True, **kwargs)

                    self.last_mode_used = label
                    return data

            except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
                err_msg = "недоступен" if isinstance(e, aiohttp.ClientConnectorError) else "таймаут"
                logger.warning("AWG [%s] %s — пробую следующий...", base_url, err_msg)
                continue
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Все URL исчерпаны
        return {
            "success": False,
            "error": (
                "⚠️ AWG Manager недоступен ни по одному адресу.\n"
                "Проверь туннель и проброс порта на роутере."
            ),
        }

    # ------------------------------------------------------------------
    # Диагностика подключения
    # ------------------------------------------------------------------

    async def probe_urls(self) -> dict[str, bool]:
        """Проверяет доступность каждого URL. Возвращает {label: ok}."""
        session = await self._get_session()
        result = {}
        pairs = [("primary", self._primary_url)]
        if self._fallback_url:
            pairs.append(("fallback", self._fallback_url))

        for label, url in pairs:
            try:
                async with session.get(
                    f"{url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    result[label] = resp.status == 200
            except Exception:
                result[label] = False
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_tunnels(self) -> dict:
        return await self._request("GET", "/tunnels/list")

    async def get_tunnel(self, tunnel_id: str) -> dict:
        return await self._request("GET", f"/tunnels/get?id={tunnel_id}")

    async def start_tunnel(self, tunnel_id: str) -> dict:
        return await self._request("POST", f"/control/start?id={tunnel_id}")

    async def stop_tunnel(self, tunnel_id: str) -> dict:
        return await self._request("POST", f"/control/stop?id={tunnel_id}")

    async def restart_tunnel(self, tunnel_id: str) -> dict:
        return await self._request("POST", f"/control/restart?id={tunnel_id}")

    async def toggle_enabled(self, tunnel_id: str) -> dict:
        return await self._request("POST", f"/control/toggle-enabled?id={tunnel_id}")

    async def get_status_all(self) -> dict:
        return await self._request("GET", "/status/all")

    async def get_wan_status(self) -> dict:
        return await self._request("GET", "/wan/status")

    async def test_connectivity(self, tunnel_id: str) -> dict:
        return await self._request("GET", f"/test/connectivity?id={tunnel_id}")

    async def test_ip(self, tunnel_id: str) -> dict:
        return await self._request("GET", f"/test/ip?id={tunnel_id}")

    async def get_pingcheck_status(self) -> dict:
        return await self._request("GET", "/pingcheck/status")

    async def get_logs(self, limit: int = 20) -> dict:
        return await self._request("GET", f"/logs?limit={limit}&group=tunnel")

    async def get_system_info(self) -> dict:
        return await self._request("GET", "/system/info")

    async def health(self) -> dict:
        return await self._request("GET", "/health")
