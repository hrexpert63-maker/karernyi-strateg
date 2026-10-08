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


INDEX_FILE = BASE / "data" / "library.json"


def _indexed() -> dict:
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def library() -> list[dict]:
    """Ручные материалы из library.yaml + видео, проиндексированные из чата клуба."""
    return _load("library.yaml") + list(_indexed().values())


def upsert_video(item: dict) -> bool:
    """Добавляет или обновляет видео. Ручное описание (/describe) не затираем подписью. True - если новое."""
    idx = _indexed()
    old = idx.get(item["id"])
    if old and old.get("manual"):
        item["summary"], item["topics"], item["manual"] = old["summary"], old["topics"], True
    idx[item["id"]] = item
    INDEX_FILE.parent.mkdir(exist_ok=True)
    INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return old is None


def describe(item_id: str, summary: str, topics: list[str] | None = None) -> bool:
    idx = _indexed()
    if item_id not in idx:
        return False
    idx[item_id]["summary"], idx[item_id]["manual"] = summary, True
    if topics is not None:
        idx[item_id]["topics"] = topics
    INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def video_item(chat_id: int, msg_id: int, caption: str, file_name: str, duration: int, date: datetime) -> dict:
    """Ссылка t.me/c/... работает для участников супергруппы."""
    lines = [l.strip() for l in (caption or "").strip().splitlines() if l.strip()]
    title = lines[0][:120] if lines else (file_name or f"Видео от {date:%d.%m.%Y}")
    internal = str(chat_id).removeprefix("-100")
    return {"id": f"tg-{msg_id}", "title": title, "type": "video", "level": "base",
            "url": f"https://t.me/c/{internal}/{msg_id}", "topics": [],
            "summary": " ".join(lines[1:])[:600] if len(lines) > 1 else "",
            "duration_min": round(duration / 60) if duration else None, "date": date.strftime("%Y-%m-%d")}


def meetings() -> list[dict]:
    items = _load("meetings.yaml")
    for m in items:
        if not isinstance(m.get("date"), datetime):
            m["date"] = datetime.fromisoformat(str(m["date"]))
    return items


def meeting(meeting_id: str) -> dict | None:
    return next((m for m in meetings() if m["id"] == meeting_id), None)


def format_item(i: dict) -> str:
    dur = f", {i['duration_min']} мин" if i.get("duration_min") else ""
    return (f"[{i['id']}] {i['title']} ({i['type']}{dur})\n"
            f"  темы: {', '.join(i.get('topics', [])) or 'не указаны'}\n"
            f"  описание: {i.get('summary') or 'нет - опирайся только на название'}\n  {i['url']}")


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
