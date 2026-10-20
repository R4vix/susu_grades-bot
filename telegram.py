"""Минимальный клиент Telegram Bot API."""
import requests

import config

API = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"


class MessageGone(Exception):
    """Сообщение, которое пытались изменить, удалено или недоступно."""


def send(chat_id: str | int, text: str) -> int:
    """Отправляет сообщение и возвращает id последней его части."""
    message_id = 0
    # Telegram ограничивает сообщение 4096 символами — режем на части.
    for i in range(0, len(text), 4000):
        resp = requests.post(
            f"{API}/sendMessage",
            json={"chat_id": chat_id, "text": text[i:i + 4000]},
            timeout=30,
        )
        resp.raise_for_status()
        message_id = resp.json()["result"]["message_id"]
    return message_id


def edit(chat_id: str | int, message_id: int, text: str) -> None:
    resp = requests.post(
        f"{API}/editMessageText",
        json={"chat_id": chat_id, "message_id": message_id, "text": text[:4000]},
        timeout=30,
    )
    if resp.status_code == 400:
        description = resp.json().get("description", "")
        # Текст тот же — менять нечего, это не ошибка.
        if "message is not modified" in description:
            return
        # Сообщение удалили или оно слишком старое — пусть вызывающий отправит новое.
        raise MessageGone(description)
    resp.raise_for_status()


def pin(chat_id: str | int, message_id: int) -> None:
    requests.post(
        f"{API}/pinChatMessage",
        json={"chat_id": chat_id, "message_id": message_id, "disable_notification": True},
        timeout=30,
    ).raise_for_status()


def get_updates(offset: int | None, timeout: int) -> list[dict]:
    params = {"timeout": timeout, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(f"{API}/getUpdates", params=params, timeout=timeout + 10)
    resp.raise_for_status()
    return resp.json().get("result", [])
