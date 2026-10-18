"""Context-aware verbalization of numbers in the Russian journal text."""
from __future__ import annotations

import re

UNITS = ("ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
TEENS = ("десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
         "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать")
TENS = {20: "двадцать", 30: "тридцать", 40: "сорок", 50: "пятьдесят", 60: "шестьдесят",
        70: "семьдесят", 80: "восемьдесят", 90: "девяносто"}
HUNDREDS = {100: "сто", 200: "двести", 300: "триста", 400: "четыреста", 500: "пятьсот",
            600: "шестьсот", 700: "семьсот", 800: "восемьсот", 900: "девятьсот"}
ORDINALS = {1: "первый", 2: "второй", 3: "третий", 4: "четвёртый", 5: "пятый", 6: "шестой",
            7: "седьмой", 8: "восьмой", 9: "девятый", 10: "десятый", 11: "одиннадцатый",
            12: "двенадцатый", 13: "тринадцатый", 14: "четырнадцатый", 15: "пятнадцатый",
            16: "шестнадцатый", 17: "семнадцатый", 18: "восемнадцатый", 19: "девятнадцатый",
            20: "двадцатый", 30: "тридцатый", 40: "сороковой", 50: "пятидесятый",
            60: "шестидесятый", 70: "семидесятый", 80: "восьмидесятый", 90: "девяностый",
            100: "сотый", 200: "двухсотый", 300: "трёхсотый", 400: "четырёхсотый",
            500: "пятисотый", 600: "шестисотый", 700: "семисотый", 800: "восьмисотый",
            900: "девятисотый", 1000: "тысячный", 2000: "двухтысячный", 3000: "трёхтысячный"}


def cardinal(number: int, *, feminine: bool = False) -> str:
    if number < 0 or number > 9999:
        raise ValueError(f"Unsupported number: {number}")
    if number < 10:
        return ("одна" if number == 1 else "две") if feminine and number in (1, 2) else UNITS[number]
    if number < 20:
        return TEENS[number - 10]
    if number < 100:
        return TENS[number // 10 * 10] + (" " + cardinal(number % 10, feminine=feminine) if number % 10 else "")
    if number < 1000:
        return HUNDREDS[number // 100 * 100] + (" " + cardinal(number % 100, feminine=feminine)
                                                    if number % 100 else "")
    thousands, rest = divmod(number, 1000)
    if thousands == 1:
        head = "тысяча"
    elif thousands == 2:
        head = "две тысячи"
    elif thousands in (3, 4):
        head = cardinal(thousands, feminine=True) + " тысячи"
    else:
        head = cardinal(thousands) + " тысяч"
    return head + (" " + cardinal(rest, feminine=feminine) if rest else "")


def ordinal(number: int, form: str = "m") -> str:
    if number in ORDINALS:
        base, prefix = ORDINALS[number], ""
    elif number < 100:
        pivot = number % 10 if number % 100 >= 20 else number % 100
        prefix, base = cardinal(number - pivot) + " ", ORDINALS[pivot]
    elif number < 1000:
        pivot = number % 100
        if pivot not in ORDINALS:
            pivot = number % 10
        prefix, base = cardinal(number - pivot) + " ", ORDINALS[pivot]
    else:
        pivot = number % 1000
        if pivot not in ORDINALS:
            pivot = number % 100
        if pivot not in ORDINALS:
            pivot = number % 10
        prefix, base = cardinal(number - pivot) + " ", ORDINALS[pivot]
    if form == "m":
        return prefix + base
    if base == "третий":
        variants = {"gen": "третьего", "prep": "третьем", "f": "третья", "fa": "третью",
                    "fg": "третьей", "n": "третье", "pl": "третьи"}
        return prefix + variants[form]
    stem = base[:-2]
    suffix = {"gen": "ого", "prep": "ом", "f": "ая", "fa": "ую", "fg": "ой", "n": "ое", "pl": "ые"}[form]
    return prefix + stem + suffix


def verbalize(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\bч\.\s+(?=\d)", "часть ", text)
    text = re.sub(r"\bн\.\s+(?=\d)", "номер ", text)
    text = text.replace("отчет", "отчёт").replace("Отчет", "Отчёт")
    # Patient record numbers, inventory codes and identifiers retain their leading zero.
    text = re.sub(r"А\.(0\d\d)", lambda m: "А, ноль " + cardinal(int(m[1])), text)
    text = re.sub(r"(?<!\w)(0\d\d)(?!\w)", lambda m: "ноль " + cardinal(int(m[1])), text)
    text = re.sub(r"С-25-1019-ДА", "С, двадцать пять, один ноль один девять, ДА", text)
    text = re.sub(r"В12\b", "В, двенадцать", text)
    text = re.sub(r"№\s*(\d+)", lambda m: "номер " + cardinal(int(m[1])), text)
    text = re.sub(r"#(\d+)", lambda m: "номер " + cardinal(int(m[1])), text)

    def year(match: re.Match[str]) -> str:
        form = {"год": "m", "года": "gen", "году": "prep", "годом": "prep"}[match[2]]
        return ordinal(int(match[1]), form) + " " + match[2]
    text = re.sub(r"\b(\d{3,4})\s+(год(?:а|у|ом)?)\b", year, text, flags=re.IGNORECASE)

    suffix_forms = {"й": "m", "я": "f", "е": "n", "го": "gen", "му": "gen",
                    "ом": "prep", "ю": "fa", "ую": "fa", "и": "pl"}
    text = re.sub(r"\b(\d+)-(го|му|ом|ую|й|я|е|ю|и)\b",
                  lambda m: ordinal(int(m[1]), suffix_forms[m[2]]), text)
    text = re.sub(r"\b(\d+)\s*%", lambda m: cardinal(int(m[1])) + " процента", text)
    text = re.sub(r"\b(\d+)\s*мм\b", lambda m: cardinal(int(m[1])) + " миллиметров", text)
    text = re.sub(r"(?m)^(\d+)\.(?=\s)", lambda m: ordinal(int(m[1]), "n") + ".", text)
    text = re.sub(r"\b(День|день)\s+(\d+)\b",
                  lambda m: m[1] + " " + ordinal(int(m[2])), text)
    text = re.sub(r"\b(запись|Запись|часть|Часть|глава|Глава)\s+(\d+)\b",
                  lambda m: m[1] + " " + ordinal(int(m[2]), "f"), text)
    text = re.sub(r"\b(\d+)\s+(минута|минуты|неделя|недели)\b",
                  lambda m: cardinal(int(m[1]), feminine=True) + " " + m[2], text)
    text = re.sub(r"\b0(\d)\s+час", lambda m: cardinal(int(m[1])) + " час", text)
    text = re.sub(r"\b(\d+)\b", lambda m: cardinal(int(m[1])), text)
    if re.search(r"\d", text):
        raise ValueError(f"Unconverted number: {text}")
    return text


if __name__ == "__main__":
    samples = {
        "3-й день, 503 год эпохи Зари": "третий день, пятьсот третий год эпохи Зари",
        "в 492 году": "в четыреста девяносто втором году",
        "45-й день, 383 год": "сорок пятый день, триста восемьдесят третий год",
        "А.053, 1 минута, 2 минуты": "А, ноль пятьдесят три, одна минута, две минуты",
        "№73; 34%; 700 мм": "номер семьдесят три; тридцать четыре процента; семьсот миллиметров",
    }
    for source, expected in samples.items():
        actual = verbalize(source)
        if actual != expected:
            raise AssertionError((source, actual, expected))
