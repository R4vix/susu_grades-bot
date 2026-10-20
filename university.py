"""Вход в «ЮУрГУ-Онлайн» (online.susu.ru) и чтение баллов из журналов текущего семестра.

fetch_grades() возвращает два словаря:
  {"Предмет — работа": "баллы"} — ключ стабилен между проверками, по нему ищутся новые и изменённые оценки;
  {"Предмет": рейтинг} — рейтинг по предмету из 100, как его показывает сайт.
"""
import json

import requests

import config

DEMO_FILE = config.BASE_DIR / "demo_grades.json"
DEMO_DEFAULT = {
    "Математический анализ — контрольная 1": "4",
    "Программирование — лабораторная 1": "зачтено",
    "История — реферат": "5",
}

# Тот же адрес, через который работает само приложение online.susu.ru.
API = "https://online.susu.ru/microgateway/api"

# Для курсовых работ и проектов журнал запрашивается с отдельным флагом.
COURSE_WORK_TYPES = {
    "96da8807-2b8b-b170-971f-430b9a19dd8a",  # курсовая работа
    "5058be9b-5bef-8e6e-07fb-acd318c1a6ce",  # курсовой проект
}
# Разделы журнала, где лежат баллы за отдельные работы.
JOURNAL_SECTIONS = ("currentControl", "labs", "courseWorksOrProjects", "bonuses", "attestation")


class LoginError(Exception):
    pass


def fetch_grades() -> tuple[dict[str, str], dict[str, float]]:
    if config.DEMO:
        return _fetch_demo(), {}
    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
    _login(session)

    term = _get(session, "/StudyActivity/StudyPlan")["currentTerm"]
    # Сервер отдаёт предметы и соседних семестров — оставляем только текущий.
    subjects = [s for s in _get(session, f"/StudyActivity/Subjects/{term}/ru") if s["termNumber"] == term]
    names = [s["disciplineName"] for s in subjects]

    grades = {}
    ratings = {}
    for subj in subjects:
        name = subj["disciplineName"]
        # Если предмет встречается дважды (например, зачёт и курсовая), различаем по форме контроля.
        if names.count(name) > 1:
            name = f"{name} ({subj['controlType']})"
        ratings[name] = subj.get("rating") or 0
        journal = _get_journal(session, subj)
        if journal is None:
            continue
        for section in JOURNAL_SECTIONS:
            for item in journal.get(section) or []:
                # 0 баллов — работа ещё не оценена: пропускаем, чтобы оценка пришла как новая.
                if not item.get("point"):
                    continue
                key = f"{name} — {item.get('name', '').strip()}"
                grades[key] = f"{_num(item['point'])} из {_num(item.get('maxPoint'))}"
    return grades, ratings


def _fetch_demo() -> dict[str, str]:
    # Чтобы проверить уведомление, отредактируйте demo_grades.json и запустите проверку.
    if not DEMO_FILE.exists():
        DEMO_FILE.write_text(
            json.dumps(DEMO_DEFAULT, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return json.loads(DEMO_FILE.read_text(encoding="utf-8"))


def _login(session: requests.Session) -> None:
    if not (config.UNI_LOGIN and config.UNI_PASSWORD):
        raise LoginError("Не заданы UNI_LOGIN и UNI_PASSWORD.")
    # Приложение отправляет форму, а не JSON: в JSON-виде сервер отвечает «Заполните все поля».
    resp = session.post(
        f"{API}/auth/login",
        data={
            "identity": "",
            "LoginForm[login]": config.UNI_LOGIN,
            "LoginForm[password]": config.UNI_PASSWORD,
        },
        timeout=60,
    )
    try:
        body = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise LoginError(f"Сайт вуза ответил не так, как ожидалось (код {resp.status_code}).")
    token = body.get("accessToken")
    if not token:
        raise LoginError(f"Сайт вуза не пустил: {body.get('message') or 'неверный логин или пароль?'}")
    session.headers["Authorization"] = f"Bearer {token}"


def _get(session: requests.Session, path: str):
    resp = session.get(API + path, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _get_journal(session: requests.Session, subj: dict) -> dict | None:
    """Журнал предмета или None, если преподаватель его ещё не создал."""
    is_course_work = str(subj["controlTypeId"] in COURSE_WORK_TYPES).lower()
    resp = session.get(
        f"{API}/StudyActivity/Journal/{subj['disciplineId']}/{subj['termNumber']}"
        f"/IsCourseWorkOrProject/{is_course_work}/ru",
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _num(value) -> str:
    """12.0 → «12», 2.5 → «2,5»."""
    if value is None:
        return "?"
    return f"{value:g}".replace(".", ",") if isinstance(value, float) else str(value)
