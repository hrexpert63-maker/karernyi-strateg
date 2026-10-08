"""Загрузка библиотеки и встреч, простая память о том, что уже публиковали."""
import json
import random
from datetime import datetime
from pathlib import Path

import yaml

BASE = Path(__file__).parent
STATE_FILE = BASE / "data" / "state.json"


def _load(name: str) -> list[dict]:
    return yaml.safe_load((BASE / "content" / name).read_text(encoding="utf-8")) or []


def library() -> list[dict]:
    return _load("library.yaml")


def meetings() -> list[dict]:
    items = _load("meetings.yaml")
    for m in items:
        if not isinstance(m.get("date"), datetime):
            m["date"] = datetime.fromisoformat(str(m["date"]))
    return items


def meeting(meeting_id: str) -> dict | None:
    return next((m for m in meetings() if m["id"] == meeting_id), None)


def format_item(i: dict) -> str:
    return (f"[{i['id']}] {i['title']} ({i['type']}, {i.get('level', 'base')})\n"
            f"  темы: {', '.join(i.get('topics', []))}\n  {i.get('summary', '')}\n  {i['url']}")


def format_library(items: list[dict] | None = None) -> str:
    items = library() if items is None else items
    return "\n".join(format_item(i) for i in items) or "(пусто)"


def related(m: dict) -> list[dict]:
    ids = set(m.get("related_library") or [])
    return [i for i in library() if i["id"] in ids]


def format_meeting(m: dict) -> str:
    return (f"id: {m['id']}\nдата и время: {m['date']:%d.%m.%Y %H:%M}\nназвание: {m['title']}\n"
            f"формат: {m.get('kind', '')}\nведёт: {m.get('speaker', '')}\n"
            f"ссылка на встречу: {m.get('link') or 'нет'}\nзапись: {m.get('recording') or 'нет'}\n"
            f"план:\n{m.get('agenda', '')}\nзаметки:\n{m.get('notes') or 'нет'}")


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"shown": {}}


def mark_shown(item_ids: list[str]) -> None:
    st = _state()
    now = datetime.now().isoformat()
    for i in item_ids:
        st["shown"][i] = now
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def pick_for_digest(n: int = 1) -> list[dict]:
    """Берём то, что дольше всего не показывали (непоказанное - первым)."""
    shown = _state()["shown"]
    items = library()
    random.shuffle(items)
    items.sort(key=lambda i: shown.get(i["id"], ""))
    return items[:n]


def upcoming(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    return sorted((m for m in meetings() if m["date"] > now), key=lambda m: m["date"])


def flag(name: str) -> bool:
    return name in _state().setdefault("flags", {})


def set_flag(name: str) -> None:
    st = _state()
    st.setdefault("flags", {})[name] = datetime.now().isoformat()
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
