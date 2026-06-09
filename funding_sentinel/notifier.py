from __future__ import annotations

import logging
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, parse_mode: str = "Markdown") -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.parse_mode = parse_mode

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, message: str) -> tuple[bool, str | None]:
        if not self.enabled:
            logger.info("Telegram not configured. Alert message:\n%s", message)
            return False, "telegram_not_configured"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": self.parse_mode,
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=15) as response:
                if 200 <= response.status < 300:
                    return True, None
                body = response.read(300).decode("utf-8", errors="replace")
                return False, f"telegram_http_{response.status}: {body}"
        except HTTPError as exc:
            body = exc.read(300).decode("utf-8", errors="replace")
            return False, f"telegram_http_{exc.code}: {body}"
        except URLError as exc:
            return False, str(exc)
