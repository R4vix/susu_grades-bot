"""Одна проверка оценок: сравнивает с прошлой и пишет в Telegram о новых.

GitHub Actions запускает этот файл по расписанию (.github/workflows/check-grades.yml).
За один запуск бот:
  - присылает новые и изменённые оценки;
  - отвечает на /start списком всех оценок (ответ приходит при ближайшей проверке);
  - обновляет закреплённое сообщение с рейтингом по предметам.

Локально:
    python check.py           — проверка с отправкой в Telegram
    python check.py --print   — проверка с выводом в консоль, без Telegram и без сохранения
"""
import json
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone

import config
import telegram
import university

# Время в закреплённом сообщении — челябинское (UTC+5), а не время сервера GitHub.
LOCAL_TZ = timezone(timedelta(hours=5))


def load_state() -> dict:
    state = {}
    if config.STATE_FILE.exists():
        state = json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    state.setdefault("grades", None)
    state.setdefault("error", None)
    # Закреплённое сообщение: его id и текст рейтингов, чтобы не редактировать без изменений.
    state.setdefault("pinned", None)
    # Номер следующего непрочитанного сообщения боту (для /start).
    state.setdefault("update_offset", None)
    return state


def save_state(state: dict) -> None:
    config.STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def percent(value: str) -> str:
    """«10,25 из 15» → « (68%)»; если баллы не в таком виде — пустая строка."""
    match = re.fullmatch(r"([\d,.]+) из ([\d,.]+)", value)
    if not match:
        return ""
    point, max_point = (float(x.replace(",", ".")) for x in match.groups())
    return f" ({point / max_point:.0%})" if max_point else ""


def rating_text(value: float) -> str:
    return f"{university._num(round(value, 2))}%"


def split_key(key: str, ratings: dict[str, float]) -> tuple[str, str]:
    """«Предмет — работа» → (предмет, работа). Предмет ищется среди известных, т.к. в названиях бывает «—»."""
    for subject in sorted(ratings, key=len, reverse=True):
        if key.startswith(subject + " — "):
            return subject, key[len(subject) + 3:]
    subject, _, work = key.partition(" — ")
    return subject, work


def format_grades(lines_by_key: dict[str, str], ratings: dict[str, float]) -> str:
    """Строки по предметам: заголовок с рейтингом предмета, под ним работы."""
    groups: dict[str, list[str]] = {}
    for key in sorted(lines_by_key):
        subject, work = split_key(key, ratings)
        # replace, а не format: в названиях работ могут встретиться фигурные скобки.
        groups.setdefault(subject, []).append(lines_by_key[key].replace("{work}", work))
    blocks = []
    for subject, lines in groups.items():
        title = f"📘 {subject}"
        if subject in ratings:
            title += f" — рейтинг по предмету {rating_text(ratings[subject])}"
        blocks.append("\n".join([title, *lines]))
    return "\n\n".join(blocks)


def all_grades_message(grades: dict[str, str], ratings: dict[str, float]) -> str:
    if not grades:
        return "Оценок пока нет. Как только появятся — пришлю."
    lines = {k: f"{{work}}: {v}{percent(v)}" for k, v in grades.items()}
    return f"Все оценки ({len(grades)}):\n\n{format_grades(lines, ratings)}"


def ratings_summary(ratings: dict[str, float]) -> str:
    """Тело закреплённого сообщения: рейтинг по каждому предмету семестра."""
    return "\n".join(f"{rating_text(r)} — {s}" for s, r in sorted(ratings.items()))


def diff(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Новые и изменённые оценки: {ключ: строка-шаблон с {work}}."""
    changes = {}
    for key, value in new.items():
        if key not in old:
            changes[key] = f"🆕 {{work}}: {value}{percent(value)}"
        elif old[key] != value:
            changes[key] = f"✏️ {{work}}: {old[key]} → {value}{percent(value)}"
    return changes


def run_check(state: dict) -> tuple[list[str], dict[str, str], dict[str, float]]:
    """Проверяет оценки и обновляет state. Возвращает (сообщения, оценки, рейтинги); при ошибке оценки пустые."""
    try:
        grades, ratings = university.fetch_grades()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        messages = []
        # Об одной и той же ошибке пишем один раз, а не каждые 30 минут.
        if state["error"] != error:
            messages.append(f"⚠️ Не получилось проверить оценки.\n{error}")
        state["error"] = error
        return messages, {}, {}

    messages = []
    if state["error"]:
        messages.append("✅ Проверка оценок снова работает.")
    state["error"] = None

    if state["grades"] is None:
        messages.append("Начал следить за оценками.\n\n" + all_grades_message(grades, ratings))
    else:
        changes = diff(state["grades"], grades)
        if changes:
            messages.append("Новые оценки:\n\n" + format_grades(changes, ratings))

    state["grades"] = grades
    return messages, grades, ratings


def answer_start(state: dict, grades: dict[str, str], ratings: dict[str, float]) -> None:
    """Отвечает на /start, пришедшие с прошлой проверки, списком всех оценок."""
    updates = telegram.get_updates(state["update_offset"], timeout=0)
    if not updates:
        return
    wants_list = False
    for update in updates:
        message = update.get("message") or {}
        # Бот личный: отвечаем только владельцу.
        if str(message.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
            continue
        if (message.get("text") or "").split("@")[0].strip() == "/start":
            wants_list = True
    if wants_list:
        telegram.send(config.TELEGRAM_CHAT_ID, all_grades_message(grades, ratings))
    # Отмечаем сообщения прочитанными только после ответа: если отправка упала, ответим в следующий раз.
    state["update_offset"] = updates[-1]["update_id"] + 1


def update_pinned(state: dict, ratings: dict[str, float]) -> None:
    """Создаёт или редактирует закреплённое сообщение с рейтингом по предметам."""
    summary = ratings_summary(ratings)
    pinned = state["pinned"]
    if pinned and pinned["summary"] == summary:
        return
    updated = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")
    text = f"📊 Рейтинг по предметам\n\n{summary}\n\nОбновлено {updated}"
    if pinned:
        try:
            telegram.edit(config.TELEGRAM_CHAT_ID, pinned["message_id"], text)
            pinned["summary"] = summary
            return
        except telegram.MessageGone:
            pass  # закреп удалили — отправим и закрепим заново
    message_id = telegram.send(config.TELEGRAM_CHAT_ID, text)
    telegram.pin(config.TELEGRAM_CHAT_ID, message_id)
    state["pinned"] = {"message_id": message_id, "summary": summary}


def main() -> None:
    to_console = "--print" in sys.argv
    if not to_console and not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID):
        sys.exit("Не заданы TELEGRAM_TOKEN и TELEGRAM_CHAT_ID (см. README.md).")

    state = load_state()
    messages, grades, ratings = run_check(state)

    if to_console:
        # Пробный запуск ничего не сохраняет и не шлёт: состояние ведёт GitHub.
        for msg in messages or ["Новых оценок нет."]:
            print(msg, end="\n\n")
        if ratings:
            print("Закреплённое сообщение:\n" + ratings_summary(ratings))
        return

    for msg in messages:
        print(msg, end="\n\n")
        # Если Telegram не ответил, скрипт упадёт до сохранения, и в следующий раз оценки придут снова.
        telegram.send(config.TELEGRAM_CHAT_ID, msg)
    save_state(state)

    # При ошибке входа оценок нет — /start подождёт до следующей удачной проверки.
    if state["error"] is None:
        try:
            answer_start(state, grades, ratings)
            if ratings:
                update_pinned(state, ratings)
        finally:
            # Сохраняем id закрепа и прочитанные /start, даже если дальше что-то упало.
            save_state(state)


if __name__ == "__main__":
    main()
