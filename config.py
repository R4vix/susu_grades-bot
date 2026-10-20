"""Настройки: из переменных окружения (секреты GitHub) или из файла .env (локальный запуск)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def _load_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_env = _load_env(ENV_FILE)


def _get(key: str, default: str = "") -> str:
    # Переменная окружения важнее .env; пустой секрет в GitHub считается незаданным.
    return os.environ.get(key) or _env.get(key) or default


TELEGRAM_TOKEN = _get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

UNI_LOGIN = _get("UNI_LOGIN")
UNI_PASSWORD = _get("UNI_PASSWORD")

# DEMO=1 — вместо сайта вуза берутся оценки из demo_grades.json (для проверки).
DEMO = _get("DEMO", "0") == "1"

# Тестовые и настоящие оценки хранятся раздельно, чтобы не смешивались.
STATE_FILE = BASE_DIR / ("state_demo.json" if DEMO else "state.json")
