#!/usr/bin/env python3
"""End-to-end variety benchmark for Aree bot graph answers."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CASES = [
    {
        "id": "salary_100k",
        "category": "curated_calc",
        "question": "ถ้าเงินเดือน 100,000 บาทต้องจ่ายภาษีปีละเท่าไหร่",
        "must": ["1,200,000", "1,040,000", "125,000"],
    },
    {
        "id": "salary_18k_age",
        "category": "curated_calc",
        "question": "ผมอายุ 22 ปี เพิ่งเริ่มทำงาน เงินเดือน 18,000 บาท ต้องยื่นภาษีไหม",
        "must": ["216,000", "56,000", "ไม่มีภาษี"],
    },
    {
        "id": "insurance_limit",
        "category": "curated_deduction",
        "question": "ประกันชีวิตลดหย่อนภาษีได้เท่าไร",
        "must": ["100,000", "25,000"],
    },
    {
        "id": "home_interest",
        "category": "curated_deduction",
        "question": "ดอกเบี้ยบ้านลดหย่อนภาษีได้หรือไม่",
        "must": ["90,000", "ดอกเบี้ย"],
    },
    {
        "id": "insurance_impact",
        "category": "curated_calc",
        "question": "ปีนี้มีรายได้ 600,000 บาท และซื้อประกันชีวิต 50,000 บาท จะช่วยลดภาษีได้เท่าไร",
        "must": ["600,000", "50,000", ["5,000", "5000"]],
    },
    {
        "id": "tcl_definition",
        "category": "curated_internal",
        "question": "TCL คืออะไร",
        "must": ["ทะเบียนคุมรายการ", "บัญชีผู้เสียภาษี"],
    },
    {
        "id": "tcl_impact",
        "category": "curated_internal",
        "question": "ถ้าระบบ TCL หยุดให้บริการ 1 วันจะกระทบอะไร",
        "must": ["ทะเบียน", "ล่าช้า"],
    },
    {
        "id": "code_9e",
        "category": "curated_code",
        "question": "9e คืออะไร",
        "must": ["ภาษีซื้อ", "ภาษีมูลค่าเพิ่ม"],
    },
    {
        "id": "sme_benefit",
        "category": "rag_callcenter",
        "question": "ธุรกิจขนาดเล็ก SME มีสิทธิประโยชน์ทางภาษีอะไรบ้าง",
        "must": [["5 ล้านบาท", "5 ล้าน", "ห้าล้าน"], ["30 ล้านบาท", "30 ล้าน", "สามสิบล้าน"], ["300,000", "สามแสน"]],
    },
    {
        "id": "influencer_wht",
        "category": "rag_callcenter",
        "question": "จ่ายเงินให้ Influencer รีวิวสินค้าต้องหัก ณ ที่จ่ายไหม",
        "must": [["ทำคนเดียว", "คนเดียว"], "เหมา", ["3%", "3 เปอร์เซ็นต์", "สามเปอร์เซ็นต์"]],
    },
    {
        "id": "car_depreciation",
        "category": "rag_callcenter",
        "question": "บริษัทซื้อรถยนต์เพื่อใช้ในกิจการ ค่าเสื่อมราคาคำนวณอย่างไร",
        "must": [["20", "ยี่สิบ"], ["1 ล้านบาท", "1,000,000", "หนึ่งล้าน"]],
    },
    {
        "id": "company_30m",
        "category": "rag_callcenter",
        "question": "รายได้บริษัทไม่ถึง 30 ล้านบาทมีอัตราภาษีพิเศษไหม",
        "must": [["5 ล้านบาท", "5 ล้าน", "ห้าล้าน"], ["30 ล้านบาท", "30 ล้าน", "สามสิบล้าน"], ["300,000", "สามแสน"]],
    },
    {
        "id": "freelance_10k_wht",
        "category": "rag_callcenter",
        "question": "รับเงิน Freelance 10,000 บาท ถูกหัก ณ ที่จ่ายกี่บาท",
        "must": [["3", "สาม"], "300"],
    },
    {
        "id": "rent_wht",
        "category": "rag_callcenter",
        "question": "ค่าเช่าทรัพย์สินถูกหัก ณ ที่จ่ายอัตราเท่าไร",
        "must": [["5", "ห้า"], "ค่าเช่า"],
    },
    {
        "id": "lawyer_wht",
        "category": "rag_callcenter",
        "question": "จ่ายค่าจ้างทนายความอิสระต้องหัก ณ ที่จ่ายกี่เปอร์เซ็นต์",
        "must": [["3", "สาม"]],
    },
    {
        "id": "royalty_foreign",
        "category": "rag_callcenter",
        "question": "รับค่า Royalty จากบริษัทต่างประเทศต้องเสียภาษีอย่างไร",
        "must": [["ค่าลิขสิทธิ์", "Royalty", "โรยัลตี้"], ["50", "ห้าสิบ"], ["100,000", "หนึ่งแสน"]],
    },
    {
        "id": "late_income_amend",
        "category": "rag_callcenter",
        "question": "ยื่นภาษีไปแล้วพบว่าลืมนำรายได้บางส่วนมารวม ต้องทำอย่างไร",
        "must": [["เพิ่มเติม", "ยกเลิกแบบ", "ยื่นแบบใหม่"]],
    },
    {
        "id": "appeal_committee",
        "category": "rag_callcenter",
        "question": "คณะกรรมการพิจารณาอุทธรณ์ภาษีอยู่ที่ไหน",
        "must": ["อุทธรณ์"],
    },
    {
        "id": "foreign_transfer",
        "category": "rag_callcenter",
        "question": "รับเงินโอนจากต่างประเทศทุกเดือนต้องเสียภาษีไหม",
        "must": ["ต่างประเทศ", "นำ"],
    },
    {
        "id": "inheritance_threshold",
        "category": "rag_callcenter",
        "question": "ได้รับมรดกเท่าไรถึงต้องเสียภาษีมรดก",
        "must": [["100 ล้านบาท", "หนึ่งร้อยล้าน"]],
    },
    {
        "id": "loan_stamp",
        "category": "rag_callcenter",
        "question": "สัญญากู้ยืมเงินต้องติดอากรแสตมป์ไหม",
        "must": ["2,000", "1 บาท", "10,000"],
    },
    {
        "id": "less_180_days",
        "category": "rag_sme_test",
        "question": "คนที่อยู่ในไทยไม่ถึง 180 วัน ต้องเสียภาษีเงินได้ในไทยไหม",
        "must": [["180", "หนึ่งร้อยแปดสิบ"], ["แหล่ง", "ต่างประเทศ"]],
    },
    {
        "id": "full_tax_invoice",
        "category": "rag_sme_test",
        "question": "ใบกำกับภาษีเต็มรูปคืออะไร",
        "must": ["ใบกำกับภาษี", "เต็มรูป"],
    },
    {
        "id": "vat_zero",
        "category": "rag_sme_test",
        "question": "อัตราภาษีมูลค่าเพิ่ม 0% ใช้กับกรณีใด",
        "must": [["0", "ศูนย์"], "ส่งออก"],
    },
    {
        "id": "cit_form_50",
        "category": "rag_sme_test",
        "question": "ใครบ้างที่มีหน้าที่ยื่นแบบ ภ.ง.ด.50",
        "must": ["นิติบุคคล", "บริษัท"],
    },
    {
        "id": "cit_form_50_due",
        "category": "rag_sme_test",
        "question": "ภ.ง.ด.50 ต้องยื่นภายในกี่วันนับจากวันสิ้นรอบบัญชี",
        "must": [["150", "หนึ่งร้อยห้าสิบ"]],
    },
    {
        "id": "no_income",
        "category": "curated_filing",
        "question": "ปีนี้ไม่มีรายได้ต้องยื่นภาษีไหม",
        "must": ["ไม่ต้อง"],
    },
    {
        "id": "late_filing",
        "category": "curated_filing",
        "question": "หากลืมยื่นภาษีเมื่อปีที่แล้ว ควรดำเนินการอย่างไร",
        "must": ["ย้อนหลัง", "ค่าปรับ"],
    },
    {
        "id": "mixed_income",
        "category": "curated_filing",
        "question": "มีรายได้จากงานประจำและฟรีแลนซ์ ต้องคำนวณภาษีอย่างไร",
        "must": ["รวม", "รายได้"],
    },
    {
        "id": "out_of_scope",
        "category": "control",
        "question": "วันนี้กินอะไรดี",
        "must": ["ภาษี"],
    },
]


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())


def passes(answer: str, must: list[str | list[str]]) -> tuple[bool, list[str]]:
    norm_answer = normalize(answer)
    missing = []
    for item in must:
        if isinstance(item, list):
            if not any(normalize(option) in norm_answer for option in item):
                missing.append(" OR ".join(item))
        elif normalize(item) not in norm_answer:
            missing.append(item)
    return not missing, missing


async def ask_graph(question: str) -> dict:
    from graph.graph import compiled_graph

    result = await compiled_graph.ainvoke(
        {
            "messages": [{"role": "user", "content": question}],
            "query": question,
            "context": "",
            "route": "direct",
            "answer": "",
            "emotion": "idle",
        }
    )
    return result


async def main() -> None:
    load_dotenv(Path.cwd() / ".env")
    started = time.perf_counter()
    results = []
    for index, case in enumerate(CASES, 1):
        before = time.perf_counter()
        try:
            graph_result = await ask_graph(case["question"])
            answer = str(graph_result.get("answer", ""))
            route = graph_result.get("route", "")
            ok, missing = passes(answer, case["must"])
            error = ""
        except Exception as exc:
            answer = ""
            route = ""
            ok = False
            missing = case["must"]
            error = repr(exc)
        elapsed_ms = round((time.perf_counter() - before) * 1000)
        item = {
            **case,
            "route": route,
            "pass": ok,
            "missing": missing,
            "elapsed_ms": elapsed_ms,
            "answer": answer,
            "error": error,
        }
        results.append(item)
        status = "PASS" if ok else "FAIL"
        print(f"[{index:02d}/{len(CASES)}] {status} {case['id']} route={route} {elapsed_ms}ms")
        if not ok:
            print(f"  missing={missing} answer={answer[:240]}")

    by_category = {}
    for item in results:
        bucket = by_category.setdefault(item["category"], {"total": 0, "pass": 0})
        bucket["total"] += 1
        bucket["pass"] += int(item["pass"])

    total = len(results)
    passed = sum(int(item["pass"]) for item in results)
    summary = {
        "questions": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "by_category": by_category,
    }

    output = {
        "summary": summary,
        "results": results,
    }
    out_path = Path("reports/e2e_variety_benchmark.json")
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
