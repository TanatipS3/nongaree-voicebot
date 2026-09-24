"""Curated exact answers for fragile short-code and form questions."""

from __future__ import annotations

import re


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zก-๙]+", "", value.lower())


_TCL_ANSWER = (
    "ระบบ TCL (ทีซีแอล) คือระบบงานทะเบียนคุมรายการและจัดทำบัญชีผู้เสียภาษีอากรของกรมสรรพากรค่ะ\n\n"
    "| หัวข้อ | รายละเอียด |\n"
    "| --- | --- |\n"
    "| หน้าที่หลัก | ดูแลทะเบียนคุมรายการและบัญชีผู้เสียภาษีอากร |\n"
    "| งานลูกหนี้ภาษี | เกี่ยวข้องกับระบบควบคุมลูกหนี้ภาษีอากรค้าง |\n"
    "| งานตามมาตรา 12 | เกี่ยวข้องกับระบบออกคำสั่งตามมาตรา 12 |\n"
    "| งานบัญชีและเงินส่งคลัง | เกี่ยวข้องกับ ACCNEW Online และระบบนำเงินส่งคลัง |\n"
    "| งานข้อมูลภายใน | สนับสนุนการประมวลผลข้อมูล การแก้ไขปัญหาระบบ และการจัดทำรายงานเพื่อใช้ปฏิบัติงาน |\n\n"
    "สรุปง่ายๆ คือ TCL ช่วยให้เจ้าหน้าที่จัดการข้อมูลทะเบียน บัญชีผู้เสียภาษี "
    "และข้อมูลประกอบการปฏิบัติงานภายในได้เป็นระบบมากขึ้นค่ะ"
)


_TCL_IMPACT_ANSWER = (
    "ถ้าระบบ TCL หยุดให้บริการ 1 วัน ผลกระทบหลักจะอยู่ที่งานทะเบียนคุมรายการ "
    "บัญชีผู้เสียภาษีอากร และระบบงานที่ต้องใช้ข้อมูลร่วมกันค่ะ\n\n"
    "| ด้านที่ได้รับผลกระทบ | ผลกระทบที่คาดว่าจะเกิดขึ้น |\n"
    "| --- | --- |\n"
    "| ทะเบียนคุมรายการและบัญชีผู้เสียภาษีอากร | เจ้าหน้าที่อาจตรวจสอบหรือปรับปรุงข้อมูลทะเบียนและบัญชีผู้เสียภาษีได้ช้าลง |\n"
    "| ระบบควบคุมลูกหนี้ภาษีอากรค้าง | งานติดตาม ตรวจสอบ หรือประมวลผลข้อมูลลูกหนี้ภาษีอาจล่าช้า |\n"
    "| ระบบออกคำสั่งตามมาตรา 12 | งานที่ต้องอ้างอิงข้อมูลจาก TCL เพื่อออกหรือจัดการคำสั่งอาจสะดุด |\n"
    "| ACCNEW Online และระบบนำเงินส่งคลัง | งานบัญชีอำเภอออนไลน์หรือการนำเงินส่งคลังที่ต้องใช้ข้อมูลเชื่อมโยงอาจทำงานได้ไม่เต็มที่ |\n"
    "| ระบบบูรณาการหนี้กรมสรรพากรและ Smart AI Assistant | ระบบที่พึ่งพาข้อมูลทะเบียนหรือข้อมูลประกอบจาก TCL อาจให้ผลลัพธ์ไม่ครบถ้วนหรือไม่ทันเวลา |\n"
    "| งานบริการและรายงานภายใน | การให้คำปรึกษา แก้ไขปัญหา จัดทำข้อมูล หรือรายงานเพื่อใช้ปฏิบัติงานอาจล่าช้า |\n\n"
    "สรุปคือ หากหยุดเพียง 1 วัน ผลกระทบมักเป็นความล่าช้าในการตรวจสอบ ประมวลผล "
    "และใช้ข้อมูลร่วมกับระบบงานภายใน มากกว่าการสรุปว่าระบบจัดเก็บภาษีทั้งหมดหยุดทำงานค่ะ"
)


def _is_tcl_topic(query: str) -> bool:
    normalized = _normalize(query)
    return any(
        marker in normalized
        for marker in (
            "tcl",
            "ทีซีแอล",
            "ทะเบียนคุมรายการ",
            "จัดทำบัญชีผู้เสียภาษี",
            "บัญชีผู้เสียภาษีอากร",
            "ควบคุมรายการผู้เสียภาษี",
            "ระบบงานทะเบียน",
        )
    )


def _is_tcl_impact_query(query: str) -> bool:
    normalized = _normalize(query)
    return _is_tcl_topic(query) and any(
        marker in normalized
        for marker in (
            "หยุด",
            "ล่ม",
            "ใช้งานไม่ได้",
            "ให้บริการไม่ได้",
            "ผลกระทบ",
            "กระทบ",
            "กระทบงาน",
            "เสียหาย",
            "1วัน",
            "หนึ่งวัน",
        )
    )


def _tcl_answer(query: str) -> tuple[str, str] | None:
    if not _is_tcl_topic(query):
        return None
    if _is_tcl_impact_query(query):
        return _TCL_IMPACT_ANSWER, "idle"
    return _TCL_ANSWER, "idle"


_ANSWERS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"(?<![0-9a-z])9e(?![0-9a-z])", re.IGNORECASE),
        "9e คือรหัสที่อ้างถึงภาษีซื้อค่ะ\n"
        "หมายถึงภาษีมูลค่าเพิ่มที่ผู้ประกอบการจดทะเบียน\n"
        "ถูกผู้ประกอบการจดทะเบียนอื่นเรียกเก็บค่ะ\n"
        "มักใช้บันทึกและหักจากภาษีขายในอี-ไฟลิ่งค่ะ",
        "idle",
    ),
    (
        re.compile(r"(?:ป\.?\s*ล\.?\s*10(?:\.1)?|ปล101)", re.IGNORECASE),
        "แบบ ป.ล.10.1 เกี่ยวกับเลขประจำตัวผู้เสียภาษีอากรค่ะ\n"
        "บุคคลธรรมดาไทยโดยทั่วไปใช้เลขบัตรประชาชน 13 หลัก\n"
        "ส่วนชาวต่างชาติใช้เลขที่กรมสรรพากรออกให้ค่ะ",
        "idle",
    ),
    (
        re.compile(r"(?:ค\.?\s*21|ค21)", re.IGNORECASE),
        "ค.21 คือหนังสือแจ้งคืนเงินภาษีเงินได้บุคคลธรรมดาค่ะ\n"
        "ถ้าไม่ได้รับหรือสูญหาย สามารถติดต่อสำนักงานสรรพากรพื้นที่\n"
        "หรือยื่นคำร้องขอออกฉบับใหม่ทางออนไลน์ได้ค่ะ",
        "happy",
    ),
]


def _format_money(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _pit_tax(taxable_income: float) -> float:
    brackets = [
        (150_000, 0.00),
        (150_000, 0.05),
        (200_000, 0.10),
        (250_000, 0.15),
        (250_000, 0.20),
        (1_000_000, 0.25),
        (3_000_000, 0.30),
        (float("inf"), 0.35),
    ]
    remaining = taxable_income
    tax = 0.0
    for width, rate in brackets:
        amount = min(remaining, width)
        if amount <= 0:
            break
        tax += amount * rate
        remaining -= amount
    return tax


def _extract_monthly_salary(query: str) -> int | None:
    salary_match = re.search(r"เงินเดือน\s*(?:ประมาณ|ราวๆ|เดือนละ)?\s*(\d[\d,]*)", query)
    if salary_match:
        return int(salary_match.group(1).replace(",", ""))

    amount_matches = [
        int(match.group(1).replace(",", ""))
        for match in re.finditer(r"(\d[\d,]*)\s*บาท", query)
    ]
    plausible_amounts = [amount for amount in amount_matches if amount >= 1_000]
    if plausible_amounts:
        return plausible_amounts[0]

    return None


def _extract_money_after(label_pattern: str, query: str) -> int | None:
    match = re.search(label_pattern + r"\s*(?:ประมาณ|ราวๆ|ปีละ|เดือนละ)?\s*(\d[\d,]*)(?:\s*บาท)?", query)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


# A salary stated as a YEARLY figure. The calculators below assume the number after
# "เงินเดือน" is monthly and multiply by 12, so "ปีนี้มีเงินเดือนรวม 600,000 บาท" became
# 7,200,000 income and ~1,979,000 tax (2026-09-14 supervisor scenario test). The marker
# must be tied to the salary amount itself: "เงินเดือน 100,000 บาทต้องจ่ายภาษีปีละเท่าไหร่"
# is monthly — its "ปีละ" belongs to the tax, not the salary.
_ANNUAL_SALARY_RE = re.compile(
    r"เงินเดือน\s*(?:รวม|ทั้งปี|ต่อปี|ปีละ|รายปี)"
    r"|(?:รวมทั้งปี|ทั้งปี|ต่อปี|ปีละ)\s*\d[\d,]*\s*บาท"
    r"|\d[\d,]*\s*บาท\s*(?:ต่อปี|/\s*ปี|ทั้งปี)"
)


def _is_annual_salary(query: str) -> bool:
    return bool(_ANNUAL_SALARY_RE.search(query))


# What each question mentions, in coarse topic groups (matched on _normalize()d text, so
# "หัก ณ ที่จ่าย" is "หักณที่จ่าย"). A canned answer only applies when the question asks
# about nothing it doesn't cover: "ThaiESG + ประกันชีวิต" used to get the insurance-only
# answer, "ฟรีแลนซ์ + หักค่าใช้จ่ายได้เท่าไร" the withholding-only one. Such questions now
# fall through to retrieval and the generator, which see the whole question.
_TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "salary": ("เงินเดือน", "ค่าจ้าง", "งานประจำ", "พนักงาน"),
    "bonus": ("โบนัส",),
    "freelance": ("ฟรีแลนซ์", "freelance", "รับงานอิสระ", "งานอิสระ"),
    "wht": ("หักณที่จ่าย", "หักที่จ่าย"),
    "expense": ("ค่าใช้จ่าย",),
    "life_insurance": ("ประกันชีวิต",),
    "health_insurance": ("ประกันสุขภาพ",),
    "social_security": ("ประกันสังคม",),
    "thaiesg_ssf": ("thaiesg", "ไทยอีเอสจี", "ssf"),
    "retirement": ("rmf", "อาร์เอ็มเอฟ", "สำรองเลี้ยงชีพ", "ประกันบำนาญ", "กองทุนรวมเพื่อการเลี้ยงชีพ"),
    "donation": ("บริจาค",),
    "home_loan": ("ดอกเบี้ยบ้าน", "ดอกเบี้ยเงินกู้"),
    "spouse_child": ("คู่สมรส", "สามี", "ภรรยา", "บุตร"),
    "vat": ("vat", "แวต", "ภาษีมูลค่าเพิ่ม"),
    "property": ("คอนโด", "อสังหา", "ที่ดิน"),
    # The freelance canned answer is about an individual RECEIVING a 3% deduction. It
    # took "จ้างฟรีแลนซ์…ใช้แบบ ภ.ง.ด. อะไร" (no form given) and "เปลี่ยนเป็นบริษัท (นิติบุคคล)
    # อัตราจะเปลี่ยนเป็นกี่ %" (answered "freelance 3%" again) in the scenario re-run.
    "juristic": ("นิติบุคคล", "บริษัท", "ห้างหุ้นส่วน"),
    "tax_form": ("ภงด", "ภพ30", "ภพ01"),
}


def _query_topics(query: str) -> set[str]:
    normalized = _normalize(query)
    return {topic for topic, terms in _TOPIC_TERMS.items() if any(t in normalized for t in terms)}


def _covers(query: str, covered: set[str]) -> bool:
    """True if every topic the question mentions is one this canned answer covers."""
    return _query_topics(query) <= covered


def _insurance_tax_impact_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if "ประกัน" not in normalized:
        return None
    if not any(term in normalized for term in ("ช่วยลดภาษี", "ลดภาษี", "เสียภาษี", "คำนวณ", "คำนวน", "เท่าไร")):
        return None

    insurance_paid = _extract_money_after(r"(?:ซื้อ)?ประกัน(?:ชีวิต)?", query)
    if insurance_paid is None:
        return None

    annual_income = _extract_money_after(r"รายได้", query)
    income_label = "รายได้ทั้งปี"
    if _is_annual_salary(query):
        return None                      # the ×12 below would inflate a yearly figure
    monthly_income = _extract_monthly_salary(query) if "เงินเดือน" in query else None
    if monthly_income is not None:
        annual_income = monthly_income * 12
        income_label = f"เงินเดือน {_format_money(monthly_income)} บาทต่อเดือน"
    if annual_income is None:
        return None

    expense = min(annual_income * 0.5, 100_000)
    personal_allowance = 60_000
    insurance_deduction = min(insurance_paid, 100_000)
    taxable_before = max(annual_income - expense - personal_allowance, 0)
    taxable_after = max(taxable_before - insurance_deduction, 0)
    tax_before = _pit_tax(taxable_before)
    tax_after = _pit_tax(taxable_after)
    tax_saving = max(tax_before - tax_after, 0)

    answer = (
        f"{income_label} รวมเป็น {_format_money(annual_income)} บาท "
        f"และซื้อประกันชีวิต {_format_money(insurance_paid)} บาทค่ะ\n"
        f"เบี้ยประกันชีวิตที่ใช้ลดหย่อนได้คือ {_format_money(insurance_deduction)} บาท "
        "เพราะไม่เกินเพดาน 100,000 บาท\n"
        f"ก่อนใช้สิทธิประกัน เงินได้สุทธิประมาณ {_format_money(taxable_before)} บาท "
        f"ภาษีประมาณ {_format_money(tax_before)} บาท\n"
        f"หลังใช้สิทธิประกัน เงินได้สุทธิประมาณ {_format_money(taxable_after)} บาท "
        f"ภาษีประมาณ {_format_money(tax_after)} บาท\n"
        f"ดังนั้นประกันชีวิตช่วยลดภาษีได้ประมาณ {_format_money(tax_saving)} บาท "
        "ภายใต้สมมติฐานว่ามีเฉพาะค่าลดหย่อนส่วนตัวและประกันชีวิตนี้ค่ะ"
    )
    return answer, "happy"


def _extract_age(query: str) -> int | None:
    match = re.search(r"อายุ\s*(\d{1,3})(?:\s*ปี)?", query)
    if not match:
        return None
    age = int(match.group(1))
    if 1 <= age <= 120:
        return age
    return None


def _salary_answer(query: str) -> tuple[str, str] | None:
    if "เงินเดือน" not in query:
        return None
    if _is_annual_salary(query):
        return None                      # this calculator is monthly-only (see _ANNUAL_SALARY_RE)

    monthly_income = _extract_monthly_salary(query)
    if monthly_income is None:
        return None

    age = _extract_age(query)
    annual_income = monthly_income * 12
    expense = min(annual_income * 0.5, 100_000)
    personal_allowance = 60_000
    taxable_income = max(annual_income - expense - personal_allowance, 0)
    tax = _pit_tax(taxable_income)
    filing_threshold = 120_000
    must_file = annual_income > filing_threshold

    if age is None:
        age_note = "ยังไม่ได้ระบุอายุ จึงคิดเฉพาะค่าลดหย่อนพื้นฐานก่อนค่ะ"
    elif age < 65:
        age_note = f"อายุ {age} ปี ยังไม่มีสิทธิยกเว้นเงินได้เพิ่มจากอายุค่ะ"
    else:
        age_note = (
            f"อายุ {age} ปี อาจมีสิทธิยกเว้นเงินได้สำหรับผู้มีอายุ 65 ปีขึ้นไปเพิ่มเติม "
            "ควรตรวจเงื่อนไขก่อนยื่นค่ะ"
        )

    if tax <= 0:
        tax_summary = "คำนวณเบื้องต้นแล้วยังไม่มีภาษีต้องชำระค่ะ"
    else:
        tax_summary = f"ภาษีประมาณ {_format_money(tax)} บาทต่อปีค่ะ"

    bonus_note = ""
    if "โบนัส" in query:
        bonus_note = (
            "\nถ้ามีโบนัส ต้องนำโบนัสไปรวมกับเงินเดือนเป็นรายได้ทั้งปีด้วยค่ะ "
            "ภาษีจริงจึงอาจสูงกว่าตัวเลขนี้ตามจำนวนโบนัสและภาษีหัก ณ ที่จ่าย"
        )

    filing_summary = (
        "รายได้ทั้งปีเกิน 120,000 บาท โดยทั่วไปควรยื่นแบบ ภ.ง.ด.91 ค่ะ"
        if must_file
        else "รายได้ทั้งปีไม่เกิน 120,000 บาท โดยทั่วไปยังไม่ถึงเกณฑ์ต้องยื่นแบบจากเงินเดือนอย่างเดียวค่ะ"
    )

    answer = (
        f"เงินเดือน {_format_money(monthly_income)} บาทต่อเดือน "
        f"ถ้ารับครบทั้งปีจะเป็น {_format_money(annual_income)} บาทค่ะ\n"
        f"{filing_summary} {tax_summary}\n"
        f"{age_note}\n"
        f"หักค่าใช้จ่ายเงินเดือนได้ {_format_money(expense)} บาท "
        f"และค่าลดหย่อนส่วนตัว {_format_money(personal_allowance)} บาท\n"
        f"เงินได้สุทธิประมาณ {_format_money(taxable_income)} บาท\n"
        "ถ้าเพิ่งเริ่มทำงานกลางปี ให้ใช้รายได้ที่ได้รับจริงทั้งปีมาคิดอีกครั้งนะคะ"
        f"{bonus_note}"
    )
    return answer, "happy"


def _insurance_deduction_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if "ประกัน" not in normalized:
        return None
    if not any(term in normalized for term in ("ลดหย่อน", "หักภาษี", "หักได้", "ภาษี")):
        return None

    spouse_terms = ("คู่สมรส", "สามี", "ภรรยา")
    if any(term in normalized for term in spouse_terms):
        answer = (
            "ถ้าเป็นเบี้ยประกันของคู่สมรส เงื่อนไขจะดูแยกจากของตัวเองค่ะ\n"
            "โดยทั่วไปต้องเป็นคู่สมรสที่จดทะเบียนสมรส และต้องไม่มีเงินได้ในปีภาษีนั้น\n"
            "คำว่าอยู่ตลอดปีภาษี หมายถึงต้องเป็นคู่สมรสกันตลอดปีภาษีที่ใช้สิทธิลดหย่อนค่ะ"
        )
        return answer, "idle"

    if any(term in normalized for term in ("ตาราง", "เปรียบเทียบ")):
        answer = (
            "ประกันชีวิตทั่วไปของตัวเองลดหย่อนได้สูงสุด 100,000 บาทต่อปีค่ะ\n"
            "ประกันสุขภาพของตัวเองลดหย่อนได้สูงสุด 25,000 บาทต่อปี\n"
            "## เปรียบเทียบสิทธิลดหย่อนประกัน\n"
            "| ประเภทประกัน | วงเงินลดหย่อน | เงื่อนไขหลัก |\n"
            "| --- | --- | --- |\n"
            "| ประกันชีวิตทั่วไป | สูงสุด 100,000 บาทต่อปี | คุ้มครองตั้งแต่ 10 ปีขึ้นไป และจ่ายจริงในปีภาษีนั้น |\n"
            "| ประกันสุขภาพตนเอง | สูงสุด 25,000 บาทต่อปี | ต้องมีหลักฐานการชำระเงิน |\n"
            "| รวมประกันชีวิต + สุขภาพตนเอง | ไม่เกิน 100,000 บาท | นับรวมอยู่ในเพดานเดียวกัน |\n"
            "\n"
            "> ประกันของพ่อแม่หรือคู่สมรสมีเงื่อนไขแยกต่างหาก"
        )
        return answer, "idle"

    answer = (
        "ประกันชีวิตทั่วไปของตัวเองลดหย่อนได้สูงสุด 100,000 บาทต่อปีค่ะ\n"
        "ประกันสุขภาพของตัวเองลดหย่อนได้สูงสุด 25,000 บาทต่อปี\n"
        "สรุปเงื่อนไขสำคัญ:\n"
        "- เมื่อรวมประกันชีวิตกับประกันสุขภาพแล้ว ต้องไม่เกิน 100,000 บาท\n"
        "- ต้องเป็นเบี้ยประกันที่จ่ายจริงในปีภาษีนั้น และมีหลักฐานการชำระเงิน\n"
        "- ประกันชีวิตทั่วไปควรมีกำหนดคุ้มครองตั้งแต่ 10 ปีขึ้นไป\n"
        "- ถ้าเป็นประกันของพ่อแม่หรือคู่สมรส จะมีเงื่อนไขแยกต่างหากค่ะ"
    )
    return answer, "idle"


def _retirement_deduction_group_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    has_retirement_terms = (
        "rmf" in normalized
        or "อาร์เอ็มเอฟ" in normalized
        or "กองทุนรวมเพื่อการเลี้ยงชีพ" in normalized
        or "กองทุนสำรองเลี้ยงชีพ" in normalized
        or "สำรองเลี้ยงชีพ" in normalized
        or "ประกันบำนาญ" in normalized
    )
    if not has_retirement_terms:
        return None
    if not any(term in normalized for term in ("ลดหย่อน", "หักภาษี", "หักได้", "สูงสุด", "เท่าไร", "ภาษี")):
        return None

    answer = (
        "กลุ่มออมเพื่อเกษียณ เช่น RMF ประกันบำนาญ และกองทุนสำรองเลี้ยงชีพ "
        "รวมกันลดหย่อนได้ไม่เกิน 500,000 บาทต่อปีค่ะ\n\n"
        "| รายการ | เพดานเฉพาะรายการ | หมายเหตุ |\n"
        "| --- | --- | --- |\n"
        "| RMF | ไม่เกิน 30% ของเงินได้ที่ต้องเสียภาษี และไม่เกิน 500,000 บาท | นับรวมในเพดานกลุ่มเกษียณ 500,000 บาท |\n"
        "| ประกันบำนาญ | ไม่เกิน 15% ของเงินได้ที่ต้องเสียภาษี และไม่เกิน 200,000 บาท | นับรวมในเพดานกลุ่มเกษียณ 500,000 บาท |\n"
        "| กองทุนสำรองเลี้ยงชีพ | ตามที่จ่ายจริง แต่ไม่เกิน 15% ของค่าจ้าง และไม่เกิน 500,000 บาท | นับรวมในเพดานกลุ่มเกษียณ 500,000 บาท |\n\n"
        "สรุปคือถึงแต่ละรายการมีเพดานย่อยของตัวเอง แต่เมื่อนำมารวมกันในกลุ่มเกษียณ "
        "โดยทั่วไปใช้สิทธิรวมสูงสุดไม่เกิน 500,000 บาทต่อปีค่ะ\n\n"
        "ควรถามต่อ:\n"
        "- รายได้ที่ต้องเสียภาษีทั้งปีเท่าไร\n"
        "- จ่าย RMF ประกันบำนาญ และกองทุนสำรองเลี้ยงชีพอย่างละเท่าไร\n"
        "- เป็นเงินสะสมกองทุนสำรองเลี้ยงชีพจากค่าจ้างปีเดียวกันหรือไม่"
    )
    return answer, "idle"


def _home_loan_interest_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if not all(term in normalized for term in ("ดอกเบี้ย", "บ้าน")):
        return None
    if not any(term in normalized for term in ("ลดหย่อน", "หักภาษี", "หักได้", "ภาษี")):
        return None

    answer = (
        "ดอกเบี้ยเงินกู้เพื่อซื้อบ้านลดหย่อนภาษีได้สูงสุด 90,000 บาทต่อปี ตามที่จ่ายจริงค่ะ\n\n"
        "| รายการ | วิธีคิด | ผลลัพธ์สูงสุด |\n"
        "| --- | --- | --- |\n"
        "| ดอกเบี้ยไม่เกิน 10,000 บาท | หักได้ตามที่จ่ายจริง | ไม่เกิน 10,000 บาท |\n"
        "| ดอกเบี้ยเกิน 10,000 บาท | หักได้เต็มจำนวนที่จ่าย แต่รวมทั้งหมดต้องไม่เกินเพดาน | 90,000 บาท |\n\n"
        "เงื่อนไขสำคัญ:\n"
        "- ต้องเป็นดอกเบี้ยเงินกู้เพื่อซื้อหรือสร้างที่อยู่อาศัย\n"
        "- ใช้ได้เฉพาะดอกเบี้ยที่จ่ายจริงในปีภาษีนั้น\n"
        "- ต้องมีหลักฐานจากสถาบันการเงิน\n"
        "- ไม่สามารถนำดอกเบี้ยจากแหล่งอื่นมารวมสิทธินี้ได้"
    )
    return answer, "idle"


def _mixed_employment_freelance_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    has_employment = any(term in normalized for term in ("งานประจำ", "เงินเดือน", "พนักงาน"))
    has_freelance = any(term in normalized for term in ("ฟรีแลนซ์", "รับงานอิสระ"))
    if not has_employment or not has_freelance:
        return None
    if not any(term in normalized for term in ("คำนวณ", "คำนวน", "ภาษี", "ยื่น")):
        return None

    answer = (
        "ถ้ามีทั้งงานประจำและฟรีแลนซ์ ต้องนำรายได้ทั้งสองส่วนมารวมคำนวณภาษีทั้งปีค่ะ\n"
        "รายได้จากงานประจำใช้เงินเดือน โบนัส และภาษีหัก ณ ที่จ่ายจากนายจ้าง\n"
        "รายได้ฟรีแลนซ์ให้รวมค่าจ้างทั้งปี แล้วหักค่าใช้จ่ายตามประเภทเงินได้หรือหลักฐานที่มี\n"
        "จากนั้นหักค่าลดหย่อน เช่น ส่วนตัว ประกัน กองทุน หรือรายการอื่นที่มีสิทธิ แล้วคำนวณภาษีแบบอัตราก้าวหน้าค่ะ"
    )
    return answer, "idle"


def _sme_company_tax_benefit_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if not all(term in normalized for term in ("บริษัท", "30ล้าน")):
        return None
    if not any(term in normalized for term in ("ภาษีพิเศษ", "อัตราภาษี", "รายได้")):
        return None

    answer = (
        "มีสิทธิประโยชน์สำหรับบริษัท SME ค่ะ แต่ต้องเข้าเงื่อนไขหลักสองข้อ\n"
        "หนึ่ง ทุนจดทะเบียนชำระแล้วในวันสุดท้ายของรอบบัญชีไม่เกิน 5 ล้านบาท\n"
        "สอง รายได้จากการขายสินค้าและให้บริการในรอบบัญชีไม่เกิน 30 ล้านบาท\n"
        "ถ้าเข้าเงื่อนไข จะได้ยกเว้นภาษีเงินได้นิติบุคคลสำหรับกำไรสุทธิ 300,000 บาทแรกค่ะ"
    )
    return answer, "idle"


def _less_than_180_days_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if "180" not in normalized and "หนึ่งร้อยแปดสิบ" not in normalized:
        return None
    if not any(term in normalized for term in ("อยู่ในไทย", "อยู่ไทย")):
        return None
    if "ภาษี" not in normalized:
        return None

    answer = (
        "ถ้าอยู่ในประเทศไทยรวมไม่ถึง 180 วันในปีภาษี โดยทั่วไปจะไม่ถือเป็นผู้อยู่ในประเทศไทยค่ะ\n"
        "แต่ยังต้องดูแหล่งที่มาของเงินได้ด้วยนะคะ\n"
        "ถ้าเป็นเงินได้จากแหล่งในประเทศไทย อาจยังต้องเสียภาษีไทยได้\n"
        "ถ้าเป็นเงินได้จากต่างประเทศและไม่ได้นำเข้ามาใช้ในไทย โดยทั่วไปไม่ต้องนำมาคำนวณภาษีไทยค่ะ"
    )
    return answer, "idle"


def _inheritance_tax_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if "มรดก" not in normalized:
        return None
    if not any(term in normalized for term in ("ภาษี", "เสีย", "เท่าไร", "เมื่อไร")):
        return None

    answer = (
        "ภาษีการรับมรดกจะเริ่มเกี่ยวเมื่อมูลค่ามรดกสุทธิที่ได้รับจากเจ้ามรดกแต่ละรายเกิน 100 ล้านบาทค่ะ\n"
        "ถ้าไม่เกิน 100 ล้านบาท โดยทั่วไปไม่ต้องเสียภาษีการรับมรดก\n"
        "ถ้าเกิน 100 ล้านบาท จะเสียเฉพาะส่วนที่เกิน 100 ล้านบาท\n"
        "อัตราภาษีคือ 5% สำหรับบุพการีหรือผู้สืบสันดาน และ 10% สำหรับผู้รับมรดกกรณีอื่นค่ะ"
    )
    return answer, "idle"


def _freelance_wht_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if not any(term in normalized for term in ("ฟรีแลนซ์", "freelance", "รับงานอิสระ")):
        return None
    if not any(term in normalized for term in ("หักณที่จ่าย", "หักที่จ่าย", "ภาษี")):
        return None

    amount = _extract_money_after(r"(?:รับเงิน|ค่าจ้าง|รายได้|เงิน)", query)
    if amount is None:
        amount = _extract_money_after(r"", query)

    if amount:
        withholding = amount * 0.03
        answer = (
            f"โดยทั่วไปค่าจ้างฟรีแลนซ์หรืองานบริการมักถูกหักภาษี ณ ที่จ่าย 3% ค่ะ\n"
            f"ถ้ารับเงิน {_format_money(amount)} บาท ภาษีหัก ณ ที่จ่ายประมาณ {_format_money(withholding)} บาท\n"
            "ผู้จ่ายควรออกหนังสือรับรองการหักภาษี ณ ที่จ่ายให้เก็บไว้ใช้ตอนยื่นภาษี\n"
            "ตอนยื่นภาษี ให้นำรายได้ทั้งปีมารวมคำนวณ และนำภาษีที่ถูกหักไว้มาเครดิตภาษีค่ะ"
        )
    else:
        answer = (
            "โดยทั่วไปค่าจ้างฟรีแลนซ์หรืองานบริการมักถูกหักภาษี ณ ที่จ่าย 3% ค่ะ\n"
            "ให้เก็บหนังสือรับรองการหักภาษี ณ ที่จ่ายไว้ใช้ตอนยื่นภาษี\n"
            "ตอนยื่นภาษี ให้นำรายได้ทั้งปีมารวมคำนวณ และนำภาษีที่ถูกหักไว้มาเครดิตภาษีค่ะ"
        )
    return answer, "idle"


def _vat_zero_rate_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if not any(term in normalized for term in ("ภาษีมูลค่าเพิ่ม", "แวต", "vat")):
        return None
    if not any(term in normalized for term in ("0", "ศูนย์")):
        return None
    if not any(term in normalized for term in ("กรณีใด", "ใช้กับ", "อัตรา")):
        return None

    answer = (
        "อัตราภาษีมูลค่าเพิ่ม 0% ใช้กับบางกรณีที่กฎหมายกำหนดค่ะ\n"
        "ตัวอย่างสำคัญคือการส่งออกสินค้า การให้บริการที่ใช้ในต่างประเทศ และการขนส่งระหว่างประเทศ\n"
        "อาจรวมถึงการขายสินค้าหรือบริการบางกรณีให้หน่วยงานหรือองค์กรที่ได้รับสิทธิตามกฎหมาย\n"
        "แม้อัตราเป็น 0% ผู้ประกอบการยังควรออกเอกสารและเก็บหลักฐานให้ครบค่ะ"
    )
    return answer, "idle"


def _no_income_filing_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if not any(term in normalized for term in ("ไม่มีรายได้", "ไม่มีเงินได้")):
        return None
    if not any(term in normalized for term in ("ยื่นภาษี", "ต้องยื่น", "ภาษี")):
        return None

    answer = (
        "ถ้าไม่มีรายได้หรือไม่มีเงินได้ถึงเกณฑ์ที่กฎหมายกำหนด โดยทั่วไปไม่ต้องยื่นภาษีค่ะ\n"
        "แต่ถ้ามีรายได้บางประเภท แม้จำนวนไม่มาก ก็ควรตรวจเกณฑ์การยื่นของปีภาษีนั้นอีกครั้ง\n"
        "ถ้าต้องการให้ชัวร์ ให้ดูรายได้ทั้งปี ประเภทเงินได้ และภาษีหัก ณ ที่จ่ายที่มีค่ะ"
    )
    return answer, "idle"


def _late_prior_year_filing_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if not all(term in normalized for term in ("ลืม", "ยื่น", "ภาษี")):
        return None
    if not any(term in normalized for term in ("ปีที่แล้ว", "ย้อนหลัง", "เลยกำหนด")):
        return None

    answer = (
        "ถ้าลืมยื่นภาษีของปีที่แล้ว ให้รีบยื่นแบบย้อนหลังโดยเร็วค่ะ\n"
        "ขั้นตอนคือเตรียมเอกสารรายได้ ภาษีหัก ณ ที่จ่าย และค่าลดหย่อนของปีนั้น\n"
        "จากนั้นยื่นผ่านอี-ไฟลิ่งหรือสำนักงานสรรพากรพื้นที่ แล้วชำระภาษีที่ขาดถ้ามี\n"
        "อาจมีค่าปรับและเงินเพิ่มตามระยะเวลาที่เลยกำหนด จึงควรดำเนินการย้อนหลังให้เร็วที่สุดค่ะ"
    )
    return answer, "idle"


def _refund_steps_answer(query: str) -> tuple[str, str] | None:
    normalized = _normalize(query)
    if not any(term in normalized for term in ("คืนภาษี", "ขอคืนภาษี", "คืนภาษีอากร")):
        return None
    if not any(term in normalized for term in ("ขั้นตอน", "ทำอย่างไร", "มีอะไรบ้าง")):
        return None

    answer = (
        "ขั้นตอนการคืนภาษีโดยสรุปคือยื่นแบบหรือคำร้องที่ระบุว่าต้องการขอคืนภาษีค่ะ\n"
        "จากนั้นกรมสรรพากรตรวจสอบข้อมูล รายได้ ภาษีที่ชำระไว้ และเอกสารประกอบ\n"
        "ถ้าข้อมูลครบและมีสิทธิคืน จะมีการอนุมัติและแจ้งผลการคืนภาษี เช่น หนังสือแจ้งคืนหรือสถานะในระบบ\n"
        "ผู้เสียภาษีสามารถตรวจสอบขั้นตอนและสถานะการคืนภาษีได้ผ่านเว็บไซต์กรมสรรพากรหรือช่องทางที่กรมกำหนดค่ะ"
    )
    return answer, "idle"


def find_curated_answer(query: str) -> tuple[str, str] | None:
    tcl = _tcl_answer(query)
    if tcl:
        return tcl

    # Each topic-specific canned answer below is guarded by _covers(): it only applies when
    # the question asks about nothing outside what that answer covers.
    insurance_tax_impact = (
        _insurance_tax_impact_answer(query)
        if _covers(query, {"salary", "life_insurance", "health_insurance"}) else None
    )
    if insurance_tax_impact:
        return insurance_tax_impact

    late_prior_year_filing = _late_prior_year_filing_answer(query)
    if late_prior_year_filing:
        return late_prior_year_filing

    refund_steps = _refund_steps_answer(query)
    if refund_steps:
        return refund_steps

    mixed_income = (
        _mixed_employment_freelance_answer(query)
        if _covers(query, {"salary", "bonus", "freelance", "wht", "expense"}) else None
    )
    if mixed_income:
        return mixed_income

    sme_company_tax_benefit = _sme_company_tax_benefit_answer(query)
    if sme_company_tax_benefit:
        return sme_company_tax_benefit

    less_than_180_days = _less_than_180_days_answer(query)
    if less_than_180_days:
        return less_than_180_days

    inheritance_tax = _inheritance_tax_answer(query)
    if inheritance_tax:
        return inheritance_tax

    freelance_wht = (
        _freelance_wht_answer(query) if _covers(query, {"freelance", "wht"}) else None
    )
    if freelance_wht:
        return freelance_wht

    vat_zero_rate = _vat_zero_rate_answer(query)
    if vat_zero_rate:
        return vat_zero_rate

    no_income_filing = _no_income_filing_answer(query)
    if no_income_filing:
        return no_income_filing

    salary = _salary_answer(query) if _covers(query, {"salary", "bonus", "expense"}) else None
    if salary:
        return salary

    retirement_deduction_group = (
        _retirement_deduction_group_answer(query) if _covers(query, {"retirement"}) else None
    )
    if retirement_deduction_group:
        return retirement_deduction_group

    insurance = (
        _insurance_deduction_answer(query)
        if _covers(query, {"life_insurance", "health_insurance", "spouse_child"}) else None
    )
    if insurance:
        return insurance

    home_loan_interest = (
        _home_loan_interest_answer(query) if _covers(query, {"home_loan"}) else None
    )
    if home_loan_interest:
        return home_loan_interest

    normalized = _normalize(query)
    for pattern, answer, emotion in _ANSWERS:
        if pattern.search(query) or pattern.search(normalized):
            return answer, emotion
    return None
