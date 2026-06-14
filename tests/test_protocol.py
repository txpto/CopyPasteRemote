from cpr_shared import protocol


def test_envelope_json_roundtrip():
    env = protocol.Envelope(
        kind=protocol.KIND_FILES,
        size=12345,
        files=[
            protocol.FileEntry("doc.txt", False, 100),
            protocol.FileEntry("photos", True, 12245),
        ],
        meta={"note": "hi"},
    )
    again = protocol.Envelope.from_json(env.to_json())
    assert again.kind == protocol.KIND_FILES
    assert again.size == 12345
    assert len(again.files) == 2
    assert again.files[1].is_dir is True
    assert again.meta["note"] == "hi"


def test_valid_slot():
    assert protocol.valid_slot(1)
    assert protocol.valid_slot(255)
    assert not protocol.valid_slot(0)
    assert not protocol.valid_slot(256)
    assert not protocol.valid_slot("3")


def test_human_summary():
    assert "text" in protocol.Envelope(kind=protocol.KIND_TEXT, size=10).human_summary()
    files = protocol.Envelope(
        kind=protocol.KIND_FILES,
        size=2048,
        files=[protocol.FileEntry("a", False, 1024), protocol.FileEntry("d", True, 1024)],
    )
    s = files.human_summary()
    assert "1 file" in s and "1 folder" in s


def test_ws_message():
    import json

    msg = json.loads(protocol.ws_message(protocol.WS_PRESENCE, slot=3, online=True))
    assert msg["type"] == protocol.WS_PRESENCE
    assert msg["slot"] == 3
    assert msg["online"] is True
    assert "ts" in msg
