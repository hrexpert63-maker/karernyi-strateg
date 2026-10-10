import sys, os
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import publisher as p


def test_split():
    text = "\n\n".join(["а" * 1500] * 5 + ["б" * 5000])
    parts = p.split_text(text, 4096)
    assert all(len(x) <= 4096 for x in parts)
    assert "".join(parts).replace("\n", "").count("а") == 7500
    assert "".join(parts).count("б") == 5000


def test_caption():
    assert p.make_caption("\n  Заголовок\nтекст") == "Заголовок"
    assert len(p.make_caption("x" * 5000)) == 1024


class FakeDrive:
    def __init__(self, age_min):
        t = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).isoformat()
        self.t = t
    def list(self, q, fields=""):
        if "mimeType" in q:
            return [{"id": "a", "name": "2026-10-04 old"}, {"id": "z", "name": "Zoom"},
                    {"id": "n", "name": "2026-10-18 11.00.00 Конференция"}]
        return [{"name": "video1.mp4", "size": "100", "modifiedTime": self.t, "id": "v"},
                {"name": "post.txt", "size": "5", "modifiedTime": self.t, "id": "p"}]


def test_find():
    ready, _ = p.find_episodes(FakeDrive(30), "root", "2026-10-11", 10)
    assert [e["name"][:10] for e in ready] == ["2026-10-18"]
    ready, notes = p.find_episodes(FakeDrive(2), "root", "2026-10-11", 10)
    assert not ready and notes
