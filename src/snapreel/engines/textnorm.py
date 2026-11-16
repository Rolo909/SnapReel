"""Text preparation for speech synthesis: numbers to words and sentence chunking.

Local TTS models skip characters they were not trained on, so "в 2026 году"
would silently lose the year. Digits are spelled out before synthesis.
"""

from __future__ import annotations

import re

_RU_ONES = ("ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать "
            "тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать").split()
_RU_TENS = " . двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто".split(" ")
_RU_HUNDREDS = " сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот".split(" ")
_RU_SCALES = (("тысяча", "тысячи", "тысяч"), ("миллион", "миллиона", "миллионов"),
              ("миллиард", "миллиарда", "миллиардов"))

_EN_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
            "fifteen sixteen seventeen eighteen nineteen").split()
_EN_TENS = " . twenty thirty forty fifty sixty seventy eighty ninety".split(" ")
_EN_SCALES = ("thousand", "million", "billion")


def _ru_triplet(n: int, feminine: bool) -> list[str]:
    words = []
    if n >= 100:
        words.append(_RU_HUNDREDS[n // 100])
    n %= 100
    if n >= 20:
        words.append(_RU_TENS[n // 10])
        n %= 10
    if n:
        word = _RU_ONES[n]
        if feminine:
            word = {"один": "одна", "два": "две"}.get(word, word)
        words.append(word)
    return words


def _ru_plural(n: int, forms: tuple[str, str, str]) -> str:
    n %= 100
    if 11 <= n <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]


def number_to_words(value: int, lang: str = "ru") -> str:
    if value < 0:
        return ("минус " if lang == "ru" else "minus ") + number_to_words(-value, lang)
    if value == 0:
        return _RU_ONES[0] if lang == "ru" else _EN_ONES[0]
    if value >= 10**12:
        return " ".join(number_to_words(int(d), lang) for d in str(value))
    groups = []
    while value:
        groups.append(value % 1000)
        value //= 1000
    words: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        n = groups[index]
        if not n:
            continue
        if lang == "ru":
            words += _ru_triplet(n, feminine=index == 1)
            if index:
                words.append(_ru_plural(n, _RU_SCALES[index - 1]))
        else:
            if n >= 100:
                words += [_EN_ONES[n // 100], "hundred"]
            rest = n % 100
            if rest >= 20:
                words.append(_EN_TENS[rest // 10] + (f"-{_EN_ONES[rest % 10]}" if rest % 10 else ""))
            elif rest:
                words.append(_EN_ONES[rest])
            if index:
                words.append(_EN_SCALES[index - 1])
    return " ".join(words)


def normalize(text: str, lang: str = "ru") -> str:
    """Spell out numbers and common symbols; collapse whitespace."""
    ru = lang == "ru"
    text = text.replace("№", " номер " if ru else " number ")
    text = re.sub(r"(\d)\s*%", r"\1 " + ("процентов" if ru else "percent"), text)
    text = re.sub(r"(\d)[.,](\d)", r"\1 " + ("и" if ru else "point") + r" \2", text)
    text = re.sub(r"(?<=\d)[\s ](?=\d{3}\b)", "", text)  # 10 000 -> 10000
    text = re.sub(r"\d+", lambda m: number_to_words(int(m.group()), lang), text)
    return re.sub(r"[ \t]+", " ", text).strip()


def detect_lang(text: str, fallback: str = "ru") -> str:
    cyr = len(re.findall(r"[а-яёА-ЯЁ]", text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    if cyr == lat == 0:
        return fallback
    return "ru" if cyr >= lat else "en"


def split_sentences(text: str, limit: int = 700) -> list[str]:
    """Split into chunks no longer than ``limit``, breaking at sentence ends when possible."""
    chunks: list[str] = []
    for paragraph in re.split(r"\n+", text):
        current = ""
        for sentence in re.split(r"(?<=[.!?…;:])\s+", paragraph.strip()):
            while len(sentence) > limit:  # one giant sentence: break at a comma or space
                cut = max(sentence.rfind(", ", 0, limit), sentence.rfind(" ", 0, limit))
                cut = cut if cut > limit // 3 else limit
                chunks.append((current + " " + sentence[:cut]).strip())
                current, sentence = "", sentence[cut:].lstrip(", ")
            if len(current) + len(sentence) + 1 > limit and current:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
    return [c for c in chunks if c.strip()]
