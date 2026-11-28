"""``app.agent_workflow.write_text``: what the kernel's cards show, moved from the old turn in 6b.  Unpatched: the moved code runs as is
(6b's acceptance found ``source_display_title`` had lost its ``uuid`` import, hidden because every caller's test patched it)."""
import uuid

from app.agent_workflow import write_text


def test_a_source_title_with_a_bad_id_is_none_and_a_good_id_is_looked_up(monkeypatch):
    assert write_text.source_display_title("uploaded_media", "not-a-uuid") is None
    looked = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, model, identity):
            looked.append((model.__name__, identity))
            return None

    monkeypatch.setattr("app.database.SessionLocal", Session)
    identity = uuid.uuid4()
    assert write_text.source_display_title("uploaded_media", str(identity)) is None
    assert looked == [("UploadedEvidence", identity)]


def test_the_two_lists_other_modules_read_are_there():
    assert "provider_timeout" in write_text.RETRYABLE_PROVIDER
    assert any(prefix.startswith("confirm") for prefix in write_text.CONTROL_PREFIXES)
