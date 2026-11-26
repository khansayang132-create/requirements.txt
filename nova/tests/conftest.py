import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore", category=UserWarning)

from nova.audio import write_wav  # noqa: E402
from nova.tts import EspeakEngine, Prosody  # noqa: E402

EN_SCRIPT = ("Welcome to our store. Discover something special today! Our team has worked for 15 years "
             "to bring you the best quality at a fair price. Do you want to save 20% on your first order? "
             "Visit us now and see the difference for yourself.")
ID_SCRIPT = ("Aku kira menikah beda negara cuma soal cinta. Ternyata aku salah. Ada satu hal tentang keluarga "
             "suamiku yang tidak pernah aku bayangkan. Kalau kamu di posisi aku, kamu tetap lanjut atau mundur?")
MIXED_SCRIPT = ("Hari ini aku mau cerita tentang culture shock. Honestly, it was harder than I thought. "
                "Tapi keluarga suamiku sangat baik dan selalu sabar sama aku.")


@pytest.fixture(scope="session")
def speaker_wav(tmp_path_factory) -> Path:
    """A synthetic 'speaker' (espeak-ng female variant): a recording nobody owns, used as an
    authorised test voice."""
    text = ("Hello, my name is Test Speaker. I am recording this sample so the studio can learn my voice. "
            "I speak clearly, with a calm and friendly tone, and I take a short pause between sentences. "
            "Thank you for listening to this recording today.")
    x, sr = EspeakEngine().synthesize(text, "en", Prosody(rate=0.95), "en-us+f3")
    return write_wav(tmp_path_factory.mktemp("rec") / "speaker.wav", x * 0.8, sr)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("NOVA_API_KEY", raising=False)
    monkeypatch.delenv("NOVA_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NOVA_SECRET_KEY", raising=False)
    from nova.config import Settings
    return Settings()


CONSENT = {"speaker_name": "Test Speaker", "relationship": "self", "consent_confirmed": "true",
           "consent_statement": "I, Test Speaker, consent to NOVA creating a voice profile from this recording."}
