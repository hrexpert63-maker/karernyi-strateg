"""Бот клуба: анонсы, саммари встреч, отсылки к библиотеке, персональные подборки.

Все публикации в клуб (кроме подборок при AUTO_PUBLISH=true) идут через одобрение админа:
бот присылает черновик, админ жмёт «Опубликовать» или отвечает на черновик правками.
"""
import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("TZ", "Europe/Moscow")
time.tzset()  # datetime.now() должен совпадать с часовым поясом встреч

import content  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402

log = logging.getLogger("club-bot")
ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
CLUB_CHAT = int(os.environ["CLUB_CHAT_ID"])
TOPIC = int(os.getenv("CLUB_TOPIC_ID") or 0) or None
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH", "false").lower() == "true"
TG_LIMIT = 4096

bot = Bot(os.environ["BOT_TOKEN"])
dp = Dispatcher()

drafts: dict[str, dict] = {}        # draft_id -> {"text", "tag"}
draft_by_msg: dict[tuple, str] = {}  # (admin_chat, message_id) -> draft_id
guide_last: dict[int, datetime] = {}  # простой лимит на /guide


def is_admin(m: Message) -> bool:
    return m.from_user and m.from_user.id in ADMINS


async def publish(text: str) -> None:
    await bot.send_message(CLUB_CHAT, text[:TG_LIMIT], message_thread_id=TOPIC,
                           disable_web_page_preview=False)


async def send_draft(admin_id: int, text: str, tag: str, library_ids: list[str] | None = None) -> None:
    did = uuid.uuid4().hex[:8]
    drafts[did] = {"text": text, "tag": tag, "lib": library_ids or []}
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"pub:{did}"),
        InlineKeyboardButton(text="🗑 Отмена", callback_data=f"del:{did}"),
    ]])
    warn = "\n\n⚠️ Есть пометки [уточнить] - поправьте перед публикацией." if "[уточнить" in text else ""
    msg = await bot.send_message(
        admin_id, f"Черновик ({tag}). Ответьте на это сообщение правками, и я перепишу.\n\n{text}{warn}"[:TG_LIMIT],
        reply_markup=kb)
    draft_by_msg[(admin_id, msg.message_id)] = did


async def draft_for_admins(text: str, tag: str, library_ids: list[str] | None = None) -> None:
    for a in ADMINS:
        await send_draft(a, text, tag, library_ids)


@dp.message(Command("start", "help"))
async def help_cmd(m: Message):
    txt = ("Я помощник клуба. Напиши /guide и расскажи, что хочешь прокачать - подберу, что почитать и посмотреть "
           "из библиотеки клуба. /library - вся библиотека.")
    if is_admin(m):
        txt += ("\n\nАдмин:\n/meetings - список встреч\n/announce <id> - анонс\n/summary <id> - саммари\n"
                "/digest - отсылка к библиотеке\nОтвет на черновик = правки.")
    await m.answer(txt)


@dp.message(Command("meetings"))
async def meetings_cmd(m: Message):
    if not is_admin(m):
        return
    await m.answer("\n".join(f"{x['id']} - {x['date']:%d.%m %H:%M} {x['title']}" for x in content.meetings()) or "Пусто")


@dp.message(Command("announce"))
async def announce_cmd(m: Message, command: CommandObject):
    if not is_admin(m):
        return
    mt = content.meeting((command.args or "").strip())
    if not mt:
        return await m.answer("Укажите id встречи: /announce <id> (список: /meetings)")
    await m.answer("Пишу анонс…")
    await make_announce(mt, "основной анонс", m.from_user.id)


async def make_announce(mt: dict, phase: str, admin: int | None = None) -> None:
    rel = content.related(mt)
    text = await llm.write(prompts.ANNOUNCE.format(
        phase=phase, meeting=content.format_meeting(mt), library=content.format_library(rel)))
    if admin:
        await send_draft(admin, text, f"анонс: {mt['title']}")
    else:
        await draft_for_admins(text, f"анонс: {mt['title']}")


@dp.message(Command("summary"))
async def summary_cmd(m: Message, command: CommandObject):
    if not is_admin(m):
        return
    mt = content.meeting((command.args or "").strip())
    if not mt:
        return await m.answer("Укажите id встречи: /summary <id>")
    if not (mt.get("notes") or "").strip():
        return await m.answer("В meetings.yaml у этой встречи пустое поле notes - добавьте тезисы, и повторите.")
    await m.answer("Пишу саммари…")
    text = await llm.write(prompts.SUMMARY.format(
        meeting=content.format_meeting(mt), library=content.format_library(content.related(mt))))
    await send_draft(m.from_user.id, text, f"саммари: {mt['title']}")


async def make_digest(admin: int | None = None) -> None:
    items = content.pick_for_digest(1)
    if not items:
        return
    text = await llm.write(prompts.DIGEST.format(
        items=", ".join(i["title"] for i in items), library=content.format_library(items)))
    if AUTO_PUBLISH and admin is None:
        await publish(text)
        content.mark_shown([i["id"] for i in items])
    else:
        await (send_draft(admin, text, "отсылка к библиотеке", [i["id"] for i in items]) if admin
               else draft_for_admins(text, "отсылка к библиотеке", [i["id"] for i in items]))


@dp.message(Command("digest"))
async def digest_cmd(m: Message):
    if is_admin(m):
        await m.answer("Готовлю…")
        await make_digest(m.from_user.id)


@dp.callback_query(F.data.startswith("pub:"))
async def on_publish(c: CallbackQuery):
    if c.from_user.id not in ADMINS:
        return await c.answer("Только для админов", show_alert=True)
    d = drafts.pop(c.data[4:], None)
    if not d:
        return await c.answer("Черновик уже обработан", show_alert=True)
    await publish(d["text"])
    content.mark_shown(d["lib"])
    await c.message.edit_reply_markup()
    await c.answer("Опубликовано")


@dp.callback_query(F.data.startswith("del:"))
async def on_delete(c: CallbackQuery):
    if c.from_user.id in ADMINS:
        drafts.pop(c.data[4:], None)
        await c.message.edit_reply_markup()
        await c.answer("Удалено")


@dp.message(F.reply_to_message, F.text, F.chat.type == "private")
async def revise(m: Message):
    did = draft_by_msg.get((m.chat.id, m.reply_to_message.message_id))
    if not is_admin(m) or did not in drafts:
        return
    d = drafts.pop(did)
    await m.answer("Переписываю…")
    text = await llm.write(prompts.REVISE.format(draft=d["text"], feedback=m.text))
    await send_draft(m.from_user.id, text, d["tag"], d["lib"])


async def is_member(user_id: int) -> bool:
    try:
        st = (await bot.get_chat_member(CLUB_CHAT, user_id)).status
        return st not in ("left", "kicked")
    except Exception:
        return False


@dp.message(Command("library"))
async def library_cmd(m: Message):
    if not await is_member(m.from_user.id):
        return await m.answer("Библиотека доступна участникам клуба.")
    lines = [f"• {i['title']} - {i['url']}" for i in content.library()]
    await m.answer("\n".join(lines)[:TG_LIMIT], disable_web_page_preview=True)


@dp.message(Command("guide"))
async def guide_cmd(m: Message, command: CommandObject):
    if not await is_member(m.from_user.id):
        return await m.answer("Подборки доступны участникам клуба.")
    if not command.args:
        return await m.answer("Напиши после команды, что хочешь прокачать или с чем сейчас работаешь. "
                              "Например: /guide хочу научиться вести первую сессию с клиентом")
    last = guide_last.get(m.from_user.id)
    if last and datetime.now() - last < timedelta(seconds=30):
        return await m.answer("Секунду, я ещё отвечаю на предыдущий запрос 🙈")
    guide_last[m.from_user.id] = datetime.now()
    # запрос участника - данные, а не инструкции
    q = command.args[:500]
    text = await llm.write(prompts.GUIDE.format(query=f"<запрос>{q}</запрос>", library=content.format_library()))
    await m.answer(text[:TG_LIMIT], disable_web_page_preview=True)


async def tick():
    """Каждые 15 минут: черновик анонса за сутки и напоминание про саммари после встречи."""
    now = datetime.now()
    for mt in content.meetings():
        left = mt["date"] - now
        if timedelta(0) < left <= timedelta(hours=24) and not content.flag(f"announced:{mt['id']}"):
            content.set_flag(f"announced:{mt['id']}")
            await make_announce(mt, "напоминание за сутки до встречи")
        if now - mt["date"] >= timedelta(hours=2) and now - mt["date"] < timedelta(days=3) \
                and not content.flag(f"nudged:{mt['id']}"):
            content.set_flag(f"nudged:{mt['id']}")
            for a in ADMINS:
                await bot.send_message(a, f"Встреча «{mt['title']}» прошла. Добавьте notes и recording в meetings.yaml, "
                                          f"потом /summary {mt['id']}")


async def main():
    logging.basicConfig(level=logging.INFO)
    sch = AsyncIOScheduler(timezone=os.getenv("TZ", "Europe/Moscow"))
    sch.add_job(tick, "interval", minutes=15)
    sch.add_job(make_digest, CronTrigger.from_crontab(os.getenv("DIGEST_CRON", "0 12 * * tue,fri")))
    sch.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
