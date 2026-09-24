"""Text normalization helpers for Thai TTS output."""

from __future__ import annotations

import re


_DIGITS = {
    "0": "ศูนย์",
    "1": "หนึ่ง",
    "2": "สอง",
    "3": "สาม",
    "4": "สี่",
    "5": "ห้า",
    "6": "หก",
    "7": "เจ็ด",
    "8": "แปด",
    "9": "เก้า",
}
_UNITS = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
_PLACES = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]
_LETTERS = {
    "a": "เอ",
    "b": "บี",
    "c": "ซี",
    "d": "ดี",
    "e": "อี",
    "f": "เอฟ",
    "g": "จี",
    "h": "เอช",
    "i": "ไอ",
    "j": "เจ",
    "k": "เค",
    "l": "แอล",
    "m": "เอ็ม",
    "n": "เอ็น",
    "o": "โอ",
    "p": "พี",
    "q": "คิว",
    "r": "อาร์",
    "s": "เอส",
    "t": "ที",
    "u": "ยู",
    "v": "วี",
    "w": "ดับเบิลยู",
    "x": "เอ็กซ์",
    "y": "วาย",
    "z": "แซด",
}


def _thai_number_under_million(value: int) -> str:
    if value == 0:
        return ""

    parts: list[str] = []
    digits = list(map(int, str(value)))
    length = len(digits)

    for index, digit in enumerate(digits):
        if digit == 0:
            continue

        place = length - index - 1
        if place == 1:
            if digit == 1:
                parts.append("สิบ")
            elif digit == 2:
                parts.append("ยี่สิบ")
            else:
                parts.append(f"{_UNITS[digit]}สิบ")
        elif place == 0:
            if digit == 1 and value > 10:
                parts.append("เอ็ด")
            else:
                parts.append(_UNITS[digit])
        else:
            parts.append(f"{_UNITS[digit]}{_PLACES[place]}")

    return "".join(parts)


def thai_number(value: int) -> str:
    if value == 0:
        return "ศูนย์"
    if value < 0:
        return f"ลบ{thai_number(abs(value))}"
    if value >= 1_000_000:
        head, tail = divmod(value, 1_000_000)
        text = f"{thai_number(head)}ล้าน"
        if tail:
            text += thai_number(tail)
        return text
    return _thai_number_under_million(value)


def _digits_as_words(text: str) -> str:
    return "".join(_DIGITS[ch] for ch in text if ch.isdigit())


def _normalize_number_token(token: str) -> str:
    compact = token.replace(",", "")
    if "." in compact:
        whole, fraction = compact.split(".", 1)
        whole_text = thai_number(int(whole)) if whole else "ศูนย์"
        return f"{whole_text}จุด{_digits_as_words(fraction)}"
    if len(compact) > 1 and compact.startswith("0"):
        return _digits_as_words(compact)
    return thai_number(int(compact))


# Hotlines that are ALWAYS a phone number, with or without a leading "โทร". 1161 is the
# RD call centre and ships inside NO_SOURCE_ANSWER, so it is spoken on every abstain
# turn; before this it was read as a quantity ("หนึ่งพันหนึ่งร้อยหกสิบเอ็ด").
_HOTLINE_CODES = ("1161", "1444")
_PHONE_CONTEXT = r"(?:เบอร์โทรศัพท์|เบอร์โทร|โทรศัพท์|สายด่วน|ติดต่อ|เบอร์|โทร|call\s*cent(?:er|re)|hotline)"
# A phone number is never followed by a unit. This keeps "1,444 บาท" a quantity.
_NOT_A_QUANTITY = r"(?!\s*(?:บาท|baht|%|เปอร์เซ็นต์|คน|ปี|เดือน|วัน))"


def _spoken_digits(digits: str) -> str:
    """Digit by digit, space separated, so TTS paces them as a phone number."""
    return " ".join(_DIGITS[ch] for ch in digits if ch.isdigit())


def normalize_phone_numbers_for_tts(text: str) -> str:
    """Speak phone numbers as separate digits, not as an amount.

    Runs BEFORE the general number rules, which would otherwise turn 1161 into
    "หนึ่งพันหนึ่งร้อยหกสิบเอ็ด" and 02-272-8000 into "ศูนย์สอง-สองร้อยเจ็ดสิบสอง-แปดพัน".
    Once a run of digits is rewritten to Thai words here, the later rules cannot see it.

    Three cases, narrowest first. Every one refuses a number carrying a unit, so amounts
    ("1,444 บาท") are untouched; the dashed and 0-leading forms are already unambiguous.
    """

    def digits_only(match: re.Match[str]) -> str:
        return _spoken_digits(match.group(0))

    # 02-272-8000, 081-234-5678, 02 272 8000 — a leading 0 makes this unambiguous.
    dashed = rf"(?<![0-9])0\d{{1,2}}[-\s]\d{{3}}[-\s]\d{{3,4}}(?![0-9]){_NOT_A_QUANTITY}"
    text = re.sub(dashed, digits_only, text)

    # 0812345678 / 022728000 written as one run.
    text = re.sub(rf"(?<![0-9])0\d{{8,9}}(?![0-9]){_NOT_A_QUANTITY}", digits_only, text)

    # "โทร 1161", "เบอร์โทร 1444", "สายด่วน 1161" — the context word carries the meaning.
    def with_context(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{_spoken_digits(match.group(3))}"

    # Only 1xxx / 1xx: every Thai short code is one (1161, 1444, 191), and restricting
    # it this way keeps a bare Buddhist year out — "ติดต่อ 2567" must stay a number.
    contextual = (
        rf"({_PHONE_CONTEXT})(\s*\.?\s*)(1\d{{2,3}})(?![0-9]){_NOT_A_QUANTITY}"
    )
    text = re.sub(contextual, with_context, text, flags=re.IGNORECASE)

    # Bare 1161 / 1444 with no context word at all. Written without a separator, so a
    # formatted amount ("1,161") never reaches here.
    bare = rf"(?<![0-9,.])({'|'.join(_HOTLINE_CODES)})(?![0-9]){_NOT_A_QUANTITY}"
    return re.sub(bare, digits_only, text)


def normalize_numbers_for_tts(text: str) -> str:
    """Convert Arabic numerals to Thai words for speech synthesis."""

    # Phone numbers first: they are digits to be READ OUT, not counted.
    text = normalize_phone_numbers_for_tts(text)

    def replace_percent(match: re.Match[str]) -> str:
        return f"{_normalize_number_token(match.group(1))}เปอร์เซ็นต์"

    def replace_spaced_money(match: re.Match[str]) -> str:
        compact = re.sub(r"[,\s]", "", match.group(1))
        return f"{thai_number(int(compact))}บาท"

    def replace_money(match: re.Match[str]) -> str:
        return f"{_normalize_number_token(match.group(1))}บาท"

    def replace_number(match: re.Match[str]) -> str:
        return _normalize_number_token(match.group(0))

    number = r"(?<![0-9A-Za-z])\d[\d,]*(?:\.\d+)?(?![0-9A-Za-z])"
    spaced_money = r"(?<![0-9A-Za-z])(\d{1,3}(?:[,\s]+\d{3,4})+)\s*(?:บาท|baht)(?![0-9A-Za-z])"
    money = fr"({number})\s*(?:บาท|baht)(?![0-9A-Za-z])"
    text = re.sub(spaced_money, replace_spaced_money, text, flags=re.IGNORECASE)
    text = re.sub(money, replace_money, text, flags=re.IGNORECASE)
    text = re.sub(fr"({number})\s*%", replace_percent, text)
    return re.sub(number, replace_number, text)


def clean_display_text(text: str) -> str:
    """Clean model text for readable chat display."""

    text = text.replace("\\n", "\n")
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.replace("ภาษีี", "ภาษี")
    text = text.replace("คำนวน", "คำนวณ")
    text = normalize_thai_number_phrases(text)
    return text.strip()


def normalize_thai_number_phrases(text: str) -> str:
    """Normalize awkward LLM-written Thai number phrases for money amounts."""

    tens = {
        "สิบ": 10,
        "ยี่สิบ": 20,
        "สามสิบ": 30,
        "สี่สิบ": 40,
        "ห้าสิบ": 50,
        "หกสิบ": 60,
        "เจ็ดสิบ": 70,
        "แปดสิบ": 80,
        "เก้าสิบ": 90,
    }
    units = {
        "": 0,
        "เอ็ด": 1,
        "หนึ่ง": 1,
        "สอง": 2,
        "สาม": 3,
        "สี่": 4,
        "ห้า": 5,
        "หก": 6,
        "เจ็ด": 7,
        "แปด": 8,
        "เก้า": 9,
    }

    def replace(match: re.Match[str]) -> str:
        ten_text = match.group(1)
        unit_text = match.group(2) or ""
        return thai_number((tens[ten_text] + units[unit_text]) * 1000)

    unit = "(เอ็ด|หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)?"
    ten_pattern = "|".join(sorted(map(re.escape, tens), key=len, reverse=True))
    text = re.sub(fr"({ten_pattern}){unit}พัน", replace, text)
    return text


def normalize_code_tokens_for_tts(text: str) -> str:
    def replace_code(match: re.Match[str]) -> str:
        token = match.group(0)
        spoken = []
        for char in token:
            if char.isdigit():
                spoken.append(_DIGITS[char])
            elif char.isalpha():
                spoken.append(_LETTERS.get(char.lower(), char))
            else:
                spoken.append(char)
        return " ".join(spoken)

    return re.sub(
        r"(?<![0-9A-Za-z])(?=[0-9A-Za-z]*\d)(?=[0-9A-Za-z]*[A-Za-z])[0-9A-Za-z]+(?![0-9A-Za-z])",
        replace_code,
        text,
    )


def normalize_thai_form_codes_for_tts(text: str) -> str:
    """Replace dotted Thai form codes with TTS-friendly phrases."""

    known_forms = {
        "90": "แบบภาษีเก้าสิบ",
        "91": "แบบภาษีเก้าสิบเอ็ด",
        "94": "แบบภาษีเก้าสิบสี่",
    }

    def replace_pnd(match: re.Match[str]) -> str:
        code = match.group(1)
        return known_forms.get(code, f"แบบภาษี{thai_number(int(code))}")

    def replace_kor(match: re.Match[str]) -> str:
        code = match.group(1)
        return f"แบบคำร้อง{thai_number(int(code))}"

    text = re.sub(r"ภ\s*\.?\s*ง\s*\.?\s*ด\s*\.?\s*(\d+)", replace_pnd, text)
    text = re.sub(r"ค\s*\.?\s*(\d+)", replace_kor, text)
    text = text.replace("แบบ แบบภาษี", "แบบภาษี")
    text = text.replace("คำร้อง แบบคำร้อง", "คำร้อง")
    return text


def normalize_for_tts(text: str) -> str:
    text = clean_display_text(text)
    text = normalize_thai_form_codes_for_tts(text)
    text = normalize_code_tokens_for_tts(text)
    text = normalize_numbers_for_tts(text)
    replacements = {
        "personal income tax": "ภาษีเงินได้บุคคลธรรมดา",
        "Personal Income Tax": "ภาษีเงินได้บุคคลธรรมดา",
        "income tax": "ภาษีเงินได้",
        "Income Tax": "ภาษีเงินได้",
        "tax from": "ภาษีจาก",
        "Tax from": "ภาษีจาก",
        "tax form": "แบบภาษี",
        "Tax form": "แบบภาษี",
        "from": "จาก",
        "From": "จาก",
        "form": "แบบ",
        "Form": "แบบ",
        "per year": "ต่อปี",
        "Per year": "ต่อปี",
        "per month": "ต่อเดือน",
        "Per month": "ต่อเดือน",
        "income": "รายได้",
        "Income": "รายได้",
        "tax": "ภาษี",
        "Tax": "ภาษี",
        "VAT": "แวต",
        "vat": "แวต",
        "e-Filing": "อี-ไฟลิ่ง",
        "E-Filing": "อี-ไฟลิ่ง",
        "e-filing": "อี-ไฟลิ่ง",
        "baht": "บาท",
        "Baht": "บาท",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"(?<=[ก-๙])\s+(บาท|ปี|เดือน|วัน|เปอร์เซ็นต์)", r"\1", text)
    return text
