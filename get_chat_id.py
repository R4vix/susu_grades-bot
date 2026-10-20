"""Узнать свой chat id: напишите боту любое сообщение, потом запустите этот файл.

    python get_chat_id.py
"""
import sys

import config
import telegram

if not config.TELEGRAM_TOKEN:
    sys.exit("Сначала впишите TELEGRAM_TOKEN в .env.")

chats = {}
for update in telegram.get_updates(offset=None, timeout=0):
    chat = update.get("message", {}).get("chat")
    if chat:
        chats[chat["id"]] = chat.get("username") or chat.get("first_name", "")

if not chats:
    print("Сообщений нет. Напишите боту что-нибудь в Telegram и запустите снова.")
for chat_id, name in chats.items():
    print(f"TELEGRAM_CHAT_ID={chat_id}   ({name})")
