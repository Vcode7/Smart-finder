"""
OCR engine choice: PP-OCRv6 first, Tesseract for Hindi lines it cannot read (or for
everything when OCR_ENGINE=tesseract / PaddleOCR is unavailable). No models are loaded.
"""
import pytest
from PIL import Image

HINDI = "भारतीय विदेश सेवा परीक्षा 1950"


@pytest.fixture
def ocr(monkeypatch):
    import app.search.model_pipeline as mp
    from app.core.config import settings
    calls = {"tesseract": 0}
    state = {"lines": None, "tesseract": "", "langs": "eng+hin"}

    def tesseract(img):
        calls["tesseract"] += 1
        return state["tesseract"]

    monkeypatch.setattr(mp, "_paddle_read", lambda img: state["lines"])
    monkeypatch.setattr(mp, "_tesseract_read", tesseract)
    monkeypatch.setattr(mp, "_ocr_languages", lambda: state["langs"])
    monkeypatch.setattr(settings, "OCR_ENGINE", "paddle")
    monkeypatch.setattr(settings, "OCR_PADDLE_MIN_CONFIDENCE", 0.80)
    img = Image.new("RGB", (200, 100), "white")
    return mp, state, calls, img, settings


def test_confident_paddle_text_is_used_as_is(ocr):
    mp, state, calls, img, _ = ocr
    state["lines"] = [("UNION PUBLIC SERVICE COMMISSION", 0.99), ("100 MILESTONES", 0.98), ("x", 0.2)]
    assert mp.run_ocr(img) == "UNION PUBLIC SERVICE COMMISSION\n100 MILESTONES"
    assert calls["tesseract"] == 0


def test_unsure_lines_are_replaced_by_tesseract_devanagari(ocr):
    mp, state, calls, img, _ = ocr
    # What PP-OCRv6 makes of a Hindi page: dates read well, names come out as look-alikes
    state["lines"] = [("16 3 2014 - 21可 2014", 0.95), ("siadeec ifaarqfam", 0.55), ("UPSC", 0.99)]
    state["tesseract"] = f"{HINDI}\nnoise 123\nश्री दीपक गुप्ता"
    text = mp.run_ocr(img)
    assert text.splitlines() == ["UPSC", HINDI, "श्री दीपक गुप्ता"]
    assert calls["tesseract"] == 1


def test_unsure_latin_text_stays_with_paddle(ocr):
    mp, state, calls, img, _ = ocr
    state["lines"] = [("CELEBRATIONS", 0.99), ("DIGNITARY LOUNGE", 0.62)]
    state["tesseract"] = "CELEBRATI0NS DlGNITARY"            # no Devanagari: ignored
    assert mp.run_ocr(img) == "CELEBRATIONS\nDIGNITARY LOUNGE"
    assert calls["tesseract"] == 1


def test_tesseract_is_not_asked_without_hindi_or_without_text(ocr):
    mp, state, calls, img, _ = ocr
    state["lines"] = [("blurry sign text", 0.6)]
    state["langs"] = "eng"
    assert mp.run_ocr(img) == "blurry sign text"
    state["langs"] = "eng+hin"
    state["lines"] = []                                     # the detector found no text at all
    state["tesseract"] = HINDI
    assert mp.run_ocr(img) == ""
    state["lines"] = [("ab", 0.3)]                          # too little unsure text to matter
    assert mp.run_ocr(img) == ""
    assert calls["tesseract"] == 0


def test_tesseract_engine_setting_and_paddle_failure(ocr):
    mp, state, calls, img, settings = ocr
    state["tesseract"] = "plain tesseract text"
    state["lines"] = None                                   # PaddleOCR could not load or failed
    assert mp.run_ocr(img) == "plain tesseract text"
    state["lines"] = [("paddle text", 0.99)]
    settings.OCR_ENGINE = "tesseract"
    assert mp.run_ocr(img) == "plain tesseract text"
    assert calls["tesseract"] == 2
