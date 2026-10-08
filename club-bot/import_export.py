"""Разовый импорт старых видео из экспорта чата (Telegram Desktop -> Экспорт истории чата -> JSON).

    python import_export.py path/to/result.json

Нужен CLUB_CHAT_ID в .env. Тема чата не учитывается: если в чате есть лишние видео - удалите их из data/library.json.
"""
import json
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()
import os  # noqa: E402

import content  # noqa: E402


def text_of(t) -> str:
    return t if isinstance(t, str) else "".join(p if isinstance(p, str) else p.get("text", "") for p in t)


def main(path: str) -> None:
    chat_id = int(os.environ["CLUB_CHAT_ID"])
    n = 0
    for msg in json.load(open(path, encoding="utf-8"))["messages"]:
        if msg.get("media_type") != "video_file" and not str(msg.get("mime_type", "")).startswith("video/"):
            continue
        item = content.video_item(chat_id, msg["id"], text_of(msg.get("text", "")), msg.get("file_name", ""),
                                  msg.get("duration_seconds", 0), datetime.fromisoformat(msg["date"]))
        n += content.upsert_video(item)
    print(f"Добавлено новых видео: {n}. Проверьте описания: запустите бота и отправьте ему /missing")


if __name__ == "__main__":
    main(sys.argv[1])
