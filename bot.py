import os
import time
import logging
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv


load_dotenv()

BASE_URL = "https://bots-api.dion.vc"
TOKEN_URL = f"{BASE_URL}/platform/v1/token"
GET_UPDATES_URL = f"{BASE_URL}/chats/v2/getUpdates"
SEND_MESSAGE_URL = f"{BASE_URL}/chats/v2/sendMessage"
SETTINGS_URL = f"{BASE_URL}/chats/v2/setMySettings"

EMAIL = os.getenv("DION_EMAIL", "").strip()
PASSWORD = os.getenv("DION_PASSWORD", "").strip()

CAN_SEND_DM = os.getenv("DION_CAN_SEND_DM", "true").lower() == "true"
CAN_JOIN_GROUPS = os.getenv("DION_CAN_JOIN_GROUPS", "true").lower() == "true"
CAN_JOIN_CHANNELS = os.getenv("DION_CAN_JOIN_CHANNELS", "false").lower() == "true"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("dion-bot")


class DionBotError(Exception):
    pass


class DionBot:
    def __init__(self, email: str, password: str) -> None:
        if not email or not password:
            raise ValueError("DION_EMAIL и DION_PASSWORD должны быть заданы")

        self.email = email
        self.password = password

        self.session = requests.Session()
        self.access_token: Optional[str] = None
        self.token_received_at: float = 0.0
        self.token_ttl_seconds: int = 11 * 60 * 60  # обновим заранее, до 12 часов
        self.offset: Optional[int] = None

    def _auth_headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise DionBotError("Токен не получен")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def refresh_token(self) -> None:
        logger.info("Запрашиваю новый access_token")
        payload = {
            "email": self.email,
            "password": self.password,
        }

        resp = self.session.post(TOKEN_URL, json=payload, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise DionBotError(f"В ответе нет access_token: {data}")

        self.access_token = token
        self.token_received_at = time.time()
        logger.info("Токен успешно получен")

    def ensure_token(self) -> None:
        if not self.access_token:
            self.refresh_token()
            return

        age = time.time() - self.token_received_at
        if age >= self.token_ttl_seconds:
            logger.info("Токен устарел, обновляю")
            self.refresh_token()

    def request_with_reauth(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
    ) -> requests.Response:
        self.ensure_token()

        for attempt in range(2):
            resp = self.session.request(
                method=method,
                url=url,
                headers=self._auth_headers(),
                params=params,
                json=json_data,
                timeout=timeout,
            )

            if resp.status_code == 401:
                logger.warning("Получен 401 Unauthorized, пробую обновить токен")
                self.refresh_token()
                continue

            return resp

        raise DionBotError("Не удалось выполнить запрос даже после обновления токена")

    def set_my_settings(
        self,
        can_send_dm: bool = True,
        can_join_groups: bool = True,
        can_join_channels: bool = False,
    ) -> None:
        payload = {
            "can_send_dm": can_send_dm,
            "can_join_groups": can_join_groups,
            "can_join_channels": can_join_channels,
        }

        resp = self.request_with_reauth(
            "POST",
            SETTINGS_URL,
            json_data=payload,
            timeout=30,
        )
        resp.raise_for_status()

        data = resp.json()
        if not data.get("ok", False):
            raise DionBotError(f"Ошибка setMySettings: {data}")

        logger.info("Настройки бота применены: %s", data.get("result"))

    def get_updates(
        self,
        timeout_seconds: int = 30,
        limit: int = 100,
        allowed_updates: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "timeout": timeout_seconds,
            "limit": limit,
        }

        if self.offset is not None:
            params["offset"] = self.offset

        # Для requests список в query можно передать так:
        if allowed_updates:
            for idx, value in enumerate(allowed_updates):
                params[f"allowed_updates[{idx}]"] = value

        resp = self.request_with_reauth(
            "GET",
            GET_UPDATES_URL,
            params=params,
            timeout=timeout_seconds + 20,
        )
        resp.raise_for_status()

        data = resp.json()
        if not data.get("ok", False):
            raise DionBotError(f"Ошибка getUpdates: {data}")

        result = data.get("result", [])
        if result:
            last_update_id = result[-1]["update_id"]
            self.offset = int(last_update_id) + 1

        return result

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        if reply_to_message_id:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id
            }

        resp = self.request_with_reauth(
            "POST",
            SEND_MESSAGE_URL,
            json_data=payload,
            timeout=30,
        )
        resp.raise_for_status()

        data = resp.json()
        if not data.get("ok", False):
            raise DionBotError(f"Ошибка sendMessage: {data}")

        return data

    def handle_message(self, message: Dict[str, Any]) -> None:
        chat = message.get("chat", {})
        from_user = message.get("from", {})
        text = (message.get("text") or "").strip()
        message_id = message.get("message_id")
        chat_id = chat.get("id")
        chat_type = chat.get("type")
        sender_name = from_user.get("name", "пользователь")

        logger.info(
            "Новое сообщение: chat_id=%s chat_type=%s sender=%s text=%r",
            chat_id, chat_type, sender_name, text
        )

        if not chat_id:
            logger.warning("Пропускаю сообщение без chat_id: %s", message)
            return

        if not text:
            self.send_message(
                chat_id=chat_id,
                text="Я получил сообщение без текста. Пока умею отвечать только на текст 🙂",
                reply_to_message_id=message_id,
            )
            return

        lowered = text.lower()

        if lowered in ("/start", "start"):
            answer = (
                f"Привет, {sender_name}!\n\n"
                "Я бот DION.\n"
                "Умею получать сообщения через getUpdates и отправлять ответы через sendMessage."
            )
        elif lowered in ("/ping", "ping"):
            answer = "pong"
        elif lowered in ("/help", "help"):
            answer = (
                "Доступные команды:\n"
                "- /start\n"
                "- /ping\n"
                "- /help\n\n"
                "Или просто напиши любой текст — я его эхо-верну."
            )
        else:
            answer = f"Ты написал: {text}"

        self.send_message(
            chat_id=chat_id,
            text=answer,
            reply_to_message_id=message_id,
        )

    def handle_update(self, update: Dict[str, Any]) -> None:
        if "message" in update:
            self.handle_message(update["message"])
            return

        if "edited_message" in update:
            logger.info("Пришло edited_message: %s", update["edited_message"])
            return

        if "my_chat_member" in update:
            logger.info("Изменение статуса бота в чате: %s", update["my_chat_member"])
            return

        if "chat_member" in update:
            logger.info("Изменение участника чата: %s", update["chat_member"])
            return

        if "message_failed" in update:
            logger.error("Ошибка сообщения: %s", update["message_failed"])
            return

        logger.warning("Неизвестный тип update: %s", update)

    def run(self) -> None:
        self.refresh_token()
        self.set_my_settings(
            can_send_dm=CAN_SEND_DM,
            can_join_groups=CAN_JOIN_GROUPS,
            can_join_channels=CAN_JOIN_CHANNELS,
        )

        logger.info("Бот запущен. Ожидаю входящие обновления...")

        allowed_updates = [
            "message",
            "edited_message",
            "my_chat_member",
            "chat_member",
            "message_failed",
        ]

        while True:
            try:
                updates = self.get_updates(
                    timeout_seconds=30,
                    limit=100,
                    allowed_updates=allowed_updates,
                )

                for update in updates:
                    try:
                        self.handle_update(update)
                    except Exception:
                        logger.exception("Ошибка обработки update: %s", update)

            except requests.HTTPError as e:
                logger.exception("HTTP ошибка: %s", e)
                time.sleep(5)

            except requests.RequestException as e:
                logger.exception("Сетевая ошибка: %s", e)
                time.sleep(5)

            except Exception as e:
                logger.exception("Непредвиденная ошибка: %s", e)
                time.sleep(5)


if __name__ == "__main__":
    bot = DionBot(EMAIL, PASSWORD)
    bot.run()