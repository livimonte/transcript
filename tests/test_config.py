from transcript.config import Settings

KEYS = ["WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE", "LANGUAGE", "SPEED_FACTOR",
        "MP3_BITRATE", "REFINE_MODEL", "REFINE_CHUNK_CHARS", "MAX_FILE_CHARS"]


def clean(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_defaults(monkeypatch):
    clean(monkeypatch)
    s = Settings.from_env()
    assert s == Settings()
    assert (s.whisper_model, s.language, s.speed_factor, s.mp3_bitrate) == ("large-v3", "pt", 2.0, "64k")
    assert (s.refine_model, s.refine_chunk_chars, s.max_file_chars) == ("claude-opus-5-5", 12000, 40000)


def test_env_and_types(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    monkeypatch.setenv("SPEED_FACTOR", "1.5")
    monkeypatch.setenv("REFINE_CHUNK_CHARS", "500")
    s = Settings.from_env()
    assert s.whisper_model == "tiny" and s.speed_factor == 1.5 and s.refine_chunk_chars == 500


def test_overrides_win_and_unknown_ignored(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    s = Settings.from_env({"whisper_model": "small", "bogus": 1, "language": None})
    assert s.whisper_model == "small" and s.language == "pt"


def test_language_reads_whisper_language_not_system_language(monkeypatch):
    from transcript.config import Settings

    monkeypatch.setenv("LANGUAGE", "pt_BR:en")
    monkeypatch.delenv("WHISPER_LANGUAGE", raising=False)
    assert Settings.from_env().language == "pt"
    monkeypatch.setenv("WHISPER_LANGUAGE", "en")
    assert Settings.from_env().language == "en"
