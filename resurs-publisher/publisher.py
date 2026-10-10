#!/usr/bin/env python3
"""Автопубликация записей эфиров клуба «Ресурс» в Telegram и ВКонтакте.

Берёт из папки эфира на Google Drive видео (.mp4) и post.txt, публикует в
Telegram-чат и в группу ВК, ставит в папке файлы-метки. Все настройки и
секреты приходят из переменных окружения (GitHub Secrets).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from requests_toolbelt.multipart.encoder import MultipartEncoder

DRIVE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3"
LOCAL_TG = "http://127.0.0.1:8081"
VK_API = "https://api.vk.com/method"
VK_VERSION = "5.199"  # сверить с актуальной документацией ВК

TG_CAPTION_LIMIT = 1024
TG_TEXT_LIMIT = 4096
VK_TEXT_LIMIT = 15000

M_PUBLISHED = "published.marker"
M_TG_VIDEO = "telegram.video"
M_TG_DONE = "telegram.done"
M_VK_VIDEO = "vk.video"
M_VK_DONE = "vk.done"


# ---------- служебное ----------

class Secrets:
    """Список секретных значений, которые нельзя печатать в логах."""
    values = []


def scrub(text):
    text = str(text)
    for v in Secrets.values:
        if v and len(v) > 5:
            text = text.replace(v, "***")
    return text


def log(msg):
    print(scrub(msg), flush=True)


def env(name, required=True, default=""):
    v = os.environ.get(name, default).strip()
    if required and not v:
        raise SystemExit(f"Не задана настройка {name} (GitHub Secret).")
    return v


def retry(fn, what, attempts=4, pause=5):
    """Повторяет fn при сетевых сбоях и ответах 5xx/429 с растущей паузой."""
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except (requests.ConnectionError, requests.Timeout, TransientError) as e:
            last = e
            log(f"  ⚠ {what}: сбой ({scrub(e)}), попытка {i}/{attempts}")
            if i < attempts:
                time.sleep(pause * i * 2)
    raise RuntimeError(f"{what}: не удалось после {attempts} попыток: {scrub(last)}")


class TransientError(Exception):
    pass


def check(resp, what):
    if resp.status_code in (429, 500, 502, 503, 504):
        raise TransientError(f"{what}: HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise RuntimeError(f"{what}: HTTP {resp.status_code}: {scrub(resp.text[:300])}")
    return resp


def split_text(text, limit):
    """Делит текст на части ≤ limit, по возможности по абзацам, затем по строкам/словам."""
    text = text.strip()
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > limit:  # абзац сам длиннее лимита
            cut = max(para.rfind("\n", 0, limit), para.rfind(" ", 0, limit))
            if cut < limit // 2:
                cut = limit
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(para[:cut].strip())
            para = para[cut:].strip()
        candidate = f"{cur}\n\n{para}" if cur else para
        if len(candidate) <= limit:
            cur = candidate
        else:
            parts.append(cur)
            cur = para
    if cur:
        parts.append(cur)
    return parts


def make_caption(text):
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first[:TG_CAPTION_LIMIT]


# ---------- Google Drive ----------

class Drive:
    def __init__(self, sa_json):
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=["https://www.googleapis.com/auth/drive"])
        self.s = AuthorizedSession(creds)

    def _get(self, url, what, **kw):
        return retry(lambda: check(self.s.get(url, timeout=60, **kw), what), what)

    def list(self, query, fields="id,name,mimeType,size,modifiedTime,createdTime"):
        out, token = [], None
        while True:
            params = {"q": query, "fields": f"nextPageToken,files({fields})", "pageSize": 200,
                      "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if token:
                params["pageToken"] = token
            data = self._get(f"{DRIVE}/files", "Drive: список файлов", params=params).json()
            out += data.get("files", [])
            token = data.get("nextPageToken")
            if not token:
                return out

    def read_text(self, file_id):
        r = self._get(f"{DRIVE}/files/{file_id}", "Drive: чтение текста",
                      params={"alt": "media", "supportsAllDrives": "true"})
        return r.content.decode("utf-8-sig")

    def download(self, file_id, dest):
        def run():
            with self.s.get(f"{DRIVE}/files/{file_id}",
                            params={"alt": "media", "supportsAllDrives": "true"},
                            stream=True, timeout=(30, 120)) as r:
                check(r, "Drive: скачивание видео")
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8 * 1024 * 1024):
                        f.write(chunk)
        retry(run, "Drive: скачивание видео", attempts=3, pause=20)

    def create_text(self, parent_id, name, content):
        boundary = "resursmarker"
        meta = json.dumps({"name": name, "parents": [parent_id]})
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                f"--{boundary}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{content}\r\n"
                f"--{boundary}--").encode("utf-8")
        retry(lambda: check(self.s.post(
            f"{DRIVE_UPLOAD}/files", params={"uploadType": "multipart", "supportsAllDrives": "true"},
            data=body, headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            timeout=60), f"Drive: создание {name}"), f"Drive: создание {name}")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def folder_date(name):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else None


def find_episodes(drive, root_id, start_date, stable_min):
    """Возвращает (готовые эфиры, сообщения о том, почему остальные пропущены)."""
    ready, notes = [], []
    folders = drive.list(f"'{root_id}' in parents and trashed=false and "
                         "mimeType='application/vnd.google-apps.folder'")
    for fo in sorted(folders, key=lambda x: x["name"]):
        name = fo["name"]
        if name.strip().lower() == "zoom":
            continue
        d = folder_date(name)
        if not d or d < start_date:
            continue
        files = drive.list(f"'{fo['id']}' in parents and trashed=false")
        by_name = {f["name"]: f for f in files}
        if M_PUBLISHED in by_name:
            continue
        mp4s = [f for f in files if f["name"].lower().endswith(".mp4")]
        if not mp4s or "post.txt" not in by_name:
            notes.append(f"{name}: ждём файлы (mp4: {'есть' if mp4s else 'нет'}, "
                         f"post.txt: {'есть' if 'post.txt' in by_name else 'нет'})")
            continue
        video = max(mp4s, key=lambda f: int(f.get("size", 0)))
        newest = max(parse_time(video["modifiedTime"]), parse_time(by_name["post.txt"]["modifiedTime"]))
        age = datetime.now(timezone.utc) - newest
        if int(video.get("size", 0)) == 0 or age < timedelta(minutes=stable_min):
            notes.append(f"{name}: файлы менялись {int(age.total_seconds() // 60)} мин назад, "
                         f"ждём {stable_min} мин без изменений")
            continue
        ready.append({"folder": fo, "name": name, "video": video,
                      "post": by_name["post.txt"], "marks": set(by_name)})
    return ready, notes


# ---------- Telegram ----------

class Telegram:
    def __init__(self, token, chat_id):
        self.token, self.chat_id = token, chat_id
        self.proc_name = "tgapi"

    def start_server(self, api_id, api_hash):
        log("Запускаю локальный Telegram Bot API server (docker)…")
        subprocess.run(["docker", "rm", "-f", self.proc_name], capture_output=True)
        subprocess.run(
            ["docker", "run", "-d", "--name", self.proc_name, "-p", "127.0.0.1:8081:8081",
             "-e", "TELEGRAM_LOCAL=1", "-e", f"TELEGRAM_API_ID={api_id}",
             "-e", f"TELEGRAM_API_HASH={api_hash}", "aiogram/telegram-bot-api:latest"],
            check=True, capture_output=True)
        for _ in range(30):
            try:
                r = requests.get(f"{LOCAL_TG}/bot{self.token}/getMe", timeout=5)
                if r.status_code == 200:
                    log(f"  сервер готов, бот: @{r.json()['result']['username']}")
                    return
                if r.status_code == 401:
                    raise RuntimeError("Telegram отклонил токен бота (TG_VIDEO_BOT_TOKEN).")
            except requests.ConnectionError:
                pass
            time.sleep(2)
        raise RuntimeError("Локальный Telegram Bot API server не запустился.")

    def stop_server(self):
        subprocess.run(["docker", "rm", "-f", self.proc_name], capture_output=True)

    def _call(self, method, what, **kw):
        def run():
            r = requests.post(f"{LOCAL_TG}/bot{self.token}/{method}", timeout=kw.pop("timeout", 60), **kw)
            check(r, what)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"{what}: {data.get('description')}")
            return data["result"]
        return retry(run, what)

    def send_video(self, path, caption):
        def run():
            with open(path, "rb") as f:
                enc = MultipartEncoder(fields={
                    "chat_id": str(self.chat_id), "caption": caption,
                    "supports_streaming": "true",
                    "video": (os.path.basename(path), f, "video/mp4")})
                r = requests.post(f"{LOCAL_TG}/bot{self.token}/sendVideo", data=enc,
                                  headers={"Content-Type": enc.content_type}, timeout=(30, 3600))
            check(r, "Telegram: отправка видео")
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram: отправка видео: {data.get('description')}")
            return data["result"]
        # повтор видео после обрыва: если до Telegram дошло — возможен дубль, поэтому 2 попытки
        return retry(run, "Telegram: отправка видео", attempts=2, pause=30)

    def send_text(self, text):
        ids = []
        for part in split_text(text, TG_TEXT_LIMIT):
            res = self._call("sendMessage", "Telegram: отправка текста",
                             data={"chat_id": self.chat_id, "text": part,
                                   "disable_web_page_preview": "true"})
            ids.append(res["message_id"])
        return ids


# ---------- ВКонтакте ----------

class VK:
    def __init__(self, token, group_id):
        self.token, self.group_id = token, group_id.lstrip("-")

    def call(self, method, what, **params):
        params["v"] = VK_VERSION
        def run():
            r = requests.post(f"{VK_API}/{method}", data=params, timeout=60,
                              headers={"Authorization": f"Bearer {self.token}"})
            check(r, what)
            data = r.json()
            if "error" in data:
                err = data["error"]
                if err.get("error_code") in (6, 9, 10):  # частота запросов/внутренняя ошибка
                    raise TransientError(f"{what}: {err.get('error_msg')}")
                raise RuntimeError(f"{what}: ВК ошибка {err.get('error_code')}: {err.get('error_msg')}")
            return data["response"]
        return retry(run, what)

    def upload_video(self, path, name, description):
        res = self.call("video.save", "ВК: video.save", group_id=self.group_id,
                        name=name[:128], description=description[:4000], wall=1)
        def run():
            with open(path, "rb") as f:
                enc = MultipartEncoder(fields={"video_file": (os.path.basename(path), f, "video/mp4")})
                r = requests.post(res["upload_url"], data=enc,
                                  headers={"Content-Type": enc.content_type}, timeout=(30, 3600))
            check(r, "ВК: загрузка видео")
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"ВК: загрузка видео: {data['error']}")
        retry(run, "ВК: загрузка видео", attempts=2, pause=30)
        return res["owner_id"], res["video_id"]

    def wall_post(self, text, owner_id, video_id):
        text = text if len(text) <= VK_TEXT_LIMIT else text[:VK_TEXT_LIMIT - 1] + "…"
        res = self.call("wall.post", "ВК: wall.post", owner_id=f"-{self.group_id}", from_group=1,
                        message=text, attachments=f"video{owner_id}_{video_id}")
        return res["post_id"]


# ---------- основной сценарий ----------

def process(ep, drive, tg, vk, tmpdir):
    name, folder_id, marks = ep["name"], ep["folder"]["id"], ep["marks"]
    post_text = drive.read_text(ep["post"]["id"]).strip()
    if not post_text:
        raise RuntimeError(f"{name}: post.txt пустой.")
    caption = make_caption(post_text)
    need_tg, need_vk = M_TG_DONE not in marks, M_VK_DONE not in marks
    errors = []
    video_path = None
    if need_tg or need_vk:
        size_mb = int(ep["video"]["size"]) / 1e6
        log(f"  скачиваю видео {ep['video']['name']} ({size_mb:.0f} МБ)…")
        video_path = os.path.join(tmpdir, "video.mp4")
        drive.download(ep["video"]["id"], video_path)

    if need_tg:
        try:
            log("  → Telegram")
            if M_TG_VIDEO not in marks:
                msg = tg.send_video(video_path, caption)
                drive.create_text(folder_id, M_TG_VIDEO, f"{now_iso()}\nmessage_id={msg['message_id']}\n")
            ids = tg.send_text(post_text)
            drive.create_text(folder_id, M_TG_DONE, f"{now_iso()}\ntext_message_ids={ids}\n")
            marks.add(M_TG_DONE)
            log("    ✓ Telegram готов")
        except Exception as e:
            errors.append(f"Telegram: {scrub(e)}")
            log(f"    ✗ {scrub(e)}")

    if need_vk:
        try:
            log("  → ВКонтакте")
            vid = None
            if M_VK_VIDEO not in marks:
                owner, video_id = vk.upload_video(video_path, caption or name, post_text)
                drive.create_text(folder_id, M_VK_VIDEO, f"{now_iso()}\nvideo={owner}_{video_id}\n")
                vid = (owner, video_id)
            else:
                txt = next(f for f in drive.list(f"'{folder_id}' in parents and name='{M_VK_VIDEO}' and trashed=false"))
                owner, video_id = drive.read_text(txt["id"]).split("video=")[1].strip().split("_")
                vid = (owner, video_id)
            post_id = vk.wall_post(post_text, *vid)
            drive.create_text(folder_id, M_VK_DONE, f"{now_iso()}\npost_id={post_id}\nvideo={vid[0]}_{vid[1]}\n")
            marks.add(M_VK_DONE)
            log("    ✓ ВК готов")
        except Exception as e:
            errors.append(f"ВК: {scrub(e)}")
            log(f"    ✗ {scrub(e)}")

    if video_path and os.path.exists(video_path):
        os.remove(video_path)
    if M_TG_DONE in marks and M_VK_DONE in marks:
        drive.create_text(folder_id, M_PUBLISHED, f"{now_iso()}\nTelegram и ВК опубликованы.\n")
        return True, []
    return False, errors


def notify(tg, chat_id, text):
    if not chat_id:
        return
    try:
        tg._call("sendMessage", "Telegram: уведомление", data={"chat_id": chat_id, "text": text})
    except Exception as e:
        log(f"  не удалось отправить уведомление: {scrub(e)}")


def main():
    dry = env("DRY_RUN", False, "false").lower() == "true"
    start_date = env("START_DATE", False, "2026-10-11")
    stable = int(env("STABLE_MINUTES", False, "10"))
    for n in ("GOOGLE_SA_JSON", "TG_VIDEO_BOT_TOKEN", "TELEGRAM_API_HASH", "VK_TOKEN"):
        Secrets.values.append(os.environ.get(n, "").strip())

    drive = Drive(env("GOOGLE_SA_JSON"))
    episodes, notes = find_episodes(drive, env("DRIVE_FOLDER_ID"), start_date, stable)
    for n in notes:
        log(f"· {n}")
    if not episodes:
        log("Новых эфиров для публикации нет.")
        return 0
    log(f"Готово к публикации эфиров: {len(episodes)}")
    for ep in episodes:
        log(f"· {ep['name']}: видео {ep['video']['name']} ({int(ep['video']['size']) / 1e6:.0f} МБ), "
            f"метки: {sorted(ep['marks'] & {M_TG_VIDEO, M_TG_DONE, M_VK_VIDEO, M_VK_DONE}) or 'нет'}")
    if dry:
        log("DRY RUN: ничего не публикуется. Было бы опубликовано в Telegram и ВК.")
        return 0

    tg = Telegram(env("TG_VIDEO_BOT_TOKEN"), env("TG_CHAT_ID"))
    vk = VK(env("VK_TOKEN"), env("VK_GROUP_ID"))
    notify_chat = env("TG_NOTIFY_CHAT_ID", False)
    failed = False
    tg.start_server(env("TELEGRAM_API_ID"), env("TELEGRAM_API_HASH"))
    try:
        for ep in episodes:
            log(f"Эфир: {ep['name']}")
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    ok, errs = process(ep, drive, tg, vk, tmp)
                except Exception as e:
                    ok, errs = False, [scrub(e)]
            if ok:
                notify(tg, notify_chat, f"✅ Эфир «{ep['name']}» опубликован в Telegram и ВК.")
            else:
                failed = True
                notify(tg, notify_chat, f"⚠️ Эфир «{ep['name']}»: публикация не завершена. "
                       f"Повтор будет при следующем запуске.\n" + "\n".join(errs))
    finally:
        tg.stop_server()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(scrub(f"Ошибка: {e}"), flush=True)
        sys.exit(1)
