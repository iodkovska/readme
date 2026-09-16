"""Conversation-flow tests: button presses, uploads and the memo handoff.

Telegram objects are faked rather than mocked wholesale, so the handlers run for
real against the state store.
"""

import asyncio
import os
from types import SimpleNamespace

import pytest

from vcbot import bot as botmod
from vcbot.analyst import AnalysisResult
from vcbot.config import Config
from vcbot.state import DealStore
from tests.test_scoring import make_memo


class FakeMessage:
    def __init__(self, text=None, document=None, photo=None):
        self.text = text
        self.document = document
        self.photo = photo or []
        self.replies: list[str] = []
        self.documents: list[str] = []
        self.captions: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(
            edit_text=self._edit, delete=self._noop, text=text
        )

    async def reply_document(self, document=None, filename=None, caption=None, **kwargs):
        self.documents.append(filename)
        self.captions.append(caption or "")
        self.document_bytes = document.getvalue() if document else b""

    async def _edit(self, text, **kwargs):
        self.replies.append(text)

    async def _noop(self, *a, **k):
        pass


class FakeUpdate:
    def __init__(self, message, chat_id=1, user_id=99):
        self.message = message
        self.effective_message = message
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.effective_user = SimpleNamespace(id=user_id)


class FakeBot:
    async def send_chat_action(self, *a, **k):
        pass


class FakeApp:
    def __init__(self, bot_data):
        self.bot_data = bot_data


class FakeContext:
    def __init__(self, bot_data, args=None):
        self.application = FakeApp(bot_data)
        self.bot = FakeBot()
        self.args = args or []


class FakeTelegramFile:
    """Stands in for a Telegram Document; writes bytes to the download path."""

    def __init__(self, file_name, payload=b"%PDF-1.4 fake", mime="application/pdf", size=100):
        self.file_name = file_name
        self.mime_type = mime
        self.file_size = size
        self._payload = payload

    async def get_file(self):
        payload = self._payload

        class Handle:
            async def download_to_drive(self, custom_path):
                with open(custom_path, "wb") as fh:
                    fh.write(payload)

        return Handle()


@pytest.fixture
def env(tmp_path):
    cfg = Config(
        telegram_token="t",
        anthropic_api_key="k",
        data_dir=tmp_path,
        allowed_user_ids=set(),
    )
    cfg.files_dir.mkdir(parents=True, exist_ok=True)
    cfg.deals_dir.mkdir(parents=True, exist_ok=True)
    store = DealStore(cfg.deals_dir)
    bot_data = {"cfg": cfg, "store": store, "analyst": None}
    return SimpleNamespace(cfg=cfg, store=store, bot_data=bot_data)


def run(coro):
    return asyncio.run(coro)


def send_text(env, text, chat_id=1, user_id=99):
    msg = FakeMessage(text=text)
    run(botmod.on_text(FakeUpdate(msg, chat_id, user_id), FakeContext(env.bot_data)))
    return msg


def send_document(env, file_name, payload=b"%PDF-1.4 fake", mime="application/pdf"):
    doc = FakeTelegramFile(file_name, payload, mime)
    msg = FakeMessage(document=doc)
    run(botmod.on_file(FakeUpdate(msg), FakeContext(env.bot_data)))
    return msg


# ------------------------------------------------------------------ button flow


def test_deck_button_then_upload(env):
    msg = send_text(env, botmod.BTN_DECK)
    assert "pitch deck" in msg.replies[0].lower()
    assert env.store.load(1).awaiting == "pitch_deck"

    upload = send_document(env, "acme_deck.pdf")
    deal = env.store.load(1)
    assert len(deal.decks) == 1
    assert deal.decks[0].file_name == "acme_deck.pdf"
    assert deal.awaiting is None
    assert "Pitch deck saved" in upload.replies[0]


def test_fin_model_button_routes_xlsx_to_models(env):
    send_text(env, botmod.BTN_MODEL)
    send_document(env, "model.xlsx", b"fake", "application/vnd.ms-excel")
    deal = env.store.load(1)
    assert len(deal.models) == 1 and not deal.decks


def test_website_button_then_url(env):
    send_text(env, botmod.BTN_WEBSITE)
    msg = send_text(env, "acme.com")
    assert env.store.load(1).websites == ["https://acme.com"]
    assert "https://acme.com" in msg.replies[0]


def test_website_button_rejects_non_url(env):
    send_text(env, botmod.BTN_WEBSITE)
    msg = send_text(env, "not a url at all")
    assert env.store.load(1).websites == []
    assert "doesn't look like a URL" in msg.replies[0]


def test_additional_info_button_then_note(env):
    send_text(env, botmod.BTN_INFO)
    send_text(env, "Founders previously built a payments company.")
    deal = env.store.load(1)
    assert deal.notes == ["Founders previously built a payments company."]
    assert deal.awaiting is None


def test_duplicate_website_is_not_stored_twice(env):
    send_text(env, "https://acme.com")
    send_text(env, "https://acme.com")
    assert env.store.load(1).websites == ["https://acme.com"]


# --------------------------------------------------------------- auto-routing


def test_pdf_without_a_button_becomes_the_deck(env):
    send_document(env, "whatever.pdf")
    assert len(env.store.load(1).decks) == 1


def test_spreadsheet_without_a_button_becomes_the_model(env):
    send_document(env, "numbers.xlsx", b"fake", "application/xlsx")
    assert len(env.store.load(1).models) == 1


def test_unknown_file_type_is_refused(env):
    msg = send_document(env, "archive.zip", b"PK", "application/zip")
    deal = env.store.load(1)
    assert not deal.decks and not deal.models
    assert "not sure what" in msg.replies[0]


def test_bare_text_becomes_a_note(env):
    send_text(env, "Intro came from a portfolio founder.")
    assert env.store.load(1).notes == ["Intro came from a portfolio founder."]


def test_text_sent_while_awaiting_a_file_is_kept_as_a_note(env):
    send_text(env, botmod.BTN_DECK)
    msg = send_text(env, "it's on the website somewhere")
    deal = env.store.load(1)
    assert deal.notes == ["it's on the website somewhere"]
    assert not deal.decks
    assert "attached file" in msg.replies[0]


def test_oversized_file_is_refused(env):
    doc = FakeTelegramFile("huge.pdf", size=env.cfg.max_file_bytes + 1)
    msg = FakeMessage(document=doc)
    run(botmod.on_file(FakeUpdate(msg), FakeContext(env.bot_data)))
    assert not env.store.load(1).decks
    assert "20 MB" in msg.replies[0]


# --------------------------------------------------------------------- memo


class FakeAnalyst:
    def __init__(self, memo=None, warnings=None, error=None, research=None, sources=None):
        self.memo = memo
        self.warnings = warnings or []
        self.error = error
        self.research = research
        self.sources = sources or []
        self.calls = 0

    def score(self, deal):
        self.calls += 1
        if self.error:
            raise self.error
        return AnalysisResult(
            memo=self.memo,
            warnings=self.warnings,
            research=self.research,
            sources=self.sources,
        )


def test_memo_requires_material(env):
    env.bot_data["analyst"] = FakeAnalyst(make_memo())
    msg = FakeMessage(text=botmod.BTN_MEMO)
    run(botmod.generate_memo(FakeUpdate(msg), FakeContext(env.bot_data)))
    assert "nothing to score" in msg.replies[0]
    assert env.bot_data["analyst"].calls == 0


def test_memo_is_rendered_and_attached(env):
    send_text(env, "Raising $3M seed.")
    analyst = FakeAnalyst(make_memo(team=9))
    env.bot_data["analyst"] = analyst

    msg = FakeMessage(text=botmod.BTN_MEMO)
    run(botmod.generate_memo(FakeUpdate(msg), FakeContext(env.bot_data)))

    assert analyst.calls == 1
    body = "\n".join(msg.replies)
    assert "Acme Robotics" in body
    assert "TRACK" in body
    assert msg.documents and msg.documents[0].endswith(".md")
    # The company name from the memo is adopted for the deal.
    assert env.store.load(1).company == "Acme Robotics"


def test_research_appendix_reaches_the_attached_file(env):
    send_text(env, "some notes")
    env.bot_data["analyst"] = FakeAnalyst(
        make_memo(),
        research="Raised a $4M seed from Index in 2024, not mentioned in the deck.",
        sources=["Crunchbase — https://crunchbase.com/acme"],
    )
    msg = FakeMessage(text=botmod.BTN_MEMO)
    run(botmod.generate_memo(FakeUpdate(msg), FakeContext(env.bot_data)))
    assert msg.documents
    assert "1 web source(s) consulted." in "\n".join(msg.captions)


def test_memo_relays_unreadable_sources(env):
    send_text(env, "https://acme.com")
    env.bot_data["analyst"] = FakeAnalyst(make_memo(), warnings=["could not reach https://acme.com"])
    msg = FakeMessage(text=botmod.BTN_MEMO)
    run(botmod.generate_memo(FakeUpdate(msg), FakeContext(env.bot_data)))
    assert any("could not reach" in r for r in msg.replies)


def test_memo_failure_is_reported_not_swallowed(env):
    send_text(env, "some notes")
    env.bot_data["analyst"] = FakeAnalyst(error=RuntimeError("API is down"))
    msg = FakeMessage(text=botmod.BTN_MEMO)
    run(botmod.generate_memo(FakeUpdate(msg), FakeContext(env.bot_data)))
    assert any("API is down" in r for r in msg.replies)


# ------------------------------------------------------------------- commands


def test_reset_clears_state_and_files(env):
    send_document(env, "deck.pdf")
    deal = env.store.load(1)
    stored = deal.decks[0].path
    assert os.path.exists(stored)

    msg = FakeMessage(text="/reset")
    run(botmod.cmd_reset(FakeUpdate(msg), FakeContext(env.bot_data)))
    assert not env.store.load(1).has_material()
    assert not os.path.exists(stored)


def test_status_lists_what_is_collected(env):
    send_document(env, "deck.pdf")
    send_text(env, "https://acme.com")
    msg = FakeMessage(text=botmod.BTN_STATUS)
    run(botmod.cmd_status(FakeUpdate(msg), FakeContext(env.bot_data)))
    reply = msg.replies[0]
    assert "✅ Pitch deck" in reply
    assert "https://acme.com" in reply
    assert "⬜ Financial model" in reply


def test_company_command_names_the_deal(env):
    msg = FakeMessage(text="/company Acme Robotics")
    run(botmod.cmd_company(FakeUpdate(msg), FakeContext(env.bot_data, args=["Acme", "Robotics"])))
    assert env.store.load(1).company == "Acme Robotics"


def test_allowlist_blocks_outsiders(env):
    env.bot_data["cfg"] = Config(
        telegram_token="t",
        anthropic_api_key="k",
        data_dir=env.cfg.data_dir,
        allowed_user_ids={1234},
    )
    msg = send_text(env, "hello", user_id=99)
    assert "private" in msg.replies[0]
    assert not env.store.load(1).has_material()


def test_allowlist_admits_members(env):
    env.bot_data["cfg"] = Config(
        telegram_token="t",
        anthropic_api_key="k",
        data_dir=env.cfg.data_dir,
        allowed_user_ids={1234},
    )
    send_text(env, "a note", user_id=1234)
    assert env.store.load(1).notes == ["a note"]


def test_two_chats_keep_separate_deals(env):
    send_text(env, "note for chat 1", chat_id=1)
    send_text(env, "note for chat 2", chat_id=2)
    assert env.store.load(1).notes == ["note for chat 1"]
    assert env.store.load(2).notes == ["note for chat 2"]
