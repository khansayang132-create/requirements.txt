"""Shared text helpers: sentence splitting, tokenising, language tagging, numbers to words."""
from __future__ import annotations

import re

WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+|\d+(?:[.,]\d+)*")
SENT_RE = re.compile(r"(?<=[.!?…])[\"'”’)]*\s+(?=[\"'“‘(]?[A-ZÀ-Ý0-9])|\n{2,}")

EN_STOP = set("""the a an and or but is are was were be been being to of in on at for with from by this that these
those it its i you he she we they my your our their me him her us them what which who whom when where why how
not no do does did have has had will would can could should may might must just very so than then there here
about into over after before because if while as all any some more most other such only own same too also
let's don't can't won't it's i'm you're we're they're isn't aren't wasn't today really thing""".split())
ID_STOP = set("""yang dan di ke dari ini itu dengan untuk tidak ada aku saya kamu kami kita mereka dia ia akan sudah
belum juga atau tapi tetapi namun karena jadi kalau jika apa siapa mana kenapa mengapa bagaimana adalah
bisa dapat harus mau ingin sangat lebih paling sekali pada oleh dalam sebagai seperti saat ketika setelah
sebelum lagi masih hanya saja pun nya kok sih dong ya nggak gak enggak banget banyak semua orang hari
ternyata menikah suami istri keluarga negara cinta beda""".split())

ONES_EN = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS_EN = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
ONES_ID = "nol satu dua tiga empat lima enam tujuh delapan sembilan sepuluh sebelas".split()


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text.strip())
    parts = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if para:
            parts.extend(s.strip() for s in SENT_RE.split(para) if s and s.strip())
    return parts


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def lang_scores(tokens: list[str]) -> tuple[int, int]:
    low = [t.lower() for t in tokens]
    return sum(t in EN_STOP for t in low), sum(t in ID_STOP for t in low)


def sentence_language(sentence: str) -> str:
    en, idn = lang_scores(words(sentence))
    if en == 0 and idn == 0:
        return "unknown"
    if en and idn and min(en, idn) / max(en, idn) >= 0.34:
        return "mixed"
    return "en" if en > idn else "id"


def _en_words(n: int) -> str:
    if n < 20:
        return ONES_EN[n]
    if n < 100:
        return TENS_EN[n // 10] + ("" if n % 10 == 0 else "-" + ONES_EN[n % 10])
    for value, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= value:
            head, rest = divmod(n, value)
            tail = "" if rest == 0 else (" and " if value == 100 else " ") + _en_words(rest)
            return f"{_en_words(head)} {name}{tail}"
    return str(n)


def _id_words(n: int) -> str:
    if n < 12:
        return ONES_ID[n]
    if n < 20:
        return f"{ONES_ID[n - 10]} belas"
    if n < 100:
        head, rest = divmod(n, 10)
        return f"{ONES_ID[head]} puluh" + ("" if rest == 0 else " " + _id_words(rest))
    if n < 200:
        return "seratus" + ("" if n == 100 else " " + _id_words(n - 100))
    if n < 1000:
        head, rest = divmod(n, 100)
        return f"{ONES_ID[head]} ratus" + ("" if rest == 0 else " " + _id_words(rest))
    if n < 2000:
        return "seribu" + ("" if n == 1000 else " " + _id_words(n - 1000))
    for value, name in ((10**9, "miliar"), (10**6, "juta"), (1000, "ribu")):
        if n >= value:
            head, rest = divmod(n, value)
            return f"{_id_words(head)} {name}" + ("" if rest == 0 else " " + _id_words(rest))
    return str(n)


def number_to_words(n: int, language: str) -> str:
    if n >= 10**12:
        return str(n)
    return _id_words(n) if language == "id" else _en_words(n)


def numbers_to_words(text: str, language: str) -> str:
    def money(m: re.Match) -> str:
        n = int(re.sub(r"[.,]", "", m.group(1)))
        return f"{number_to_words(n, 'id')} rupiah"

    text = re.sub(r"\bRp\.?\s?(\d{1,3}(?:[.,]\d{3})+|\d+)\b", money, text)
    text = re.sub(r"(\d+)\s?%", lambda m: f"{m.group(1)} {'persen' if language == 'id' else 'percent'}", text)
    sep = "." if language == "id" else ","

    def plain(m: re.Match) -> str:
        raw = m.group(0)
        if re.fullmatch(rf"\d{{1,3}}(?:\{sep}\d{{3}})+", raw):
            return number_to_words(int(raw.replace(sep, "")), language)
        if raw.isdigit():
            if len(raw) == 4 and 1900 <= int(raw) <= 2099 and language == "en":
                hi, lo = divmod(int(raw), 100)
                return _en_words(hi) + " " + ("hundred" if lo == 0 else ("oh " + ONES_EN[lo] if lo < 10 else _en_words(lo)))
            return number_to_words(int(raw), language)
        return raw

    return re.sub(r"\d{1,3}(?:[.,]\d{3})+|\d+", plain, text)
