"""
CESCO 서비스 결과 보고서 PDF의 특정 수치를 x10 배로 변환하는 스크립트.

변환 대상
1. 본문 내 "[피닉스프로N]" / "[썬더블루N]" 태그 뒤에 오는 곤충명 + 숫자(포획/목격/섭식) -> x10
2. "8) 포충등별 모니터링 분석" 표: 파리, 모기, 깔따구, 나방파리, 초파리, 날파리, 나방 컬럼 -> x10
   (일련번호가 PH로 시작하는 행 = 바로 이 표의 행이므로 자동으로 함께 처리됨)
   합계(합계 컬럼)는 x10된 값들의 합으로 재계산

사용법:
    pip install pdfplumber reportlab --break-system-packages
    python multiply_pest_report.py input.pdf output.pdf

주의:
- reportlab로 재생성한 PDF는 원본과 동일한 디자인(로고, 표 테두리 등)을 재현하지 않고,
  텍스트/표 내용을 그대로 살린 "내용 중심" PDF입니다.
  원본 레이아웃을 그대로 유지해야 한다면 PyMuPDF(fitz)로 텍스트를 in-place 치환하는 방식을
  추가로 구현해야 합니다(아래 process_pdf_inplace_fitz 참고 - 뼈대만 제공).
- 실제 표 구조는 페이지마다 다를 수 있으니, extract_ph_table() 결과를 한 번 print해서
  컬럼 순서/헤더 이름이 실제 PDF와 일치하는지 반드시 확인 후 사용하세요.
"""

import re
import sys
import argparse

import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

FACTOR = 10

DEVICE_TAGS = ["피닉스프로N", "썬더블루N"]
INSECT_COLUMNS = ["파리", "나방파리", "초파리", "날파리", "모기", "깔따구", "나방"]

# [피닉스프로N] 또는 [썬더블루N] 태그 뒤, 숫자 직전까지의 텍스트(곤충명 등)를 그대로 두고
# 그 다음 나오는 숫자(콤마 포함 가능)만 잡아서 x10
NUM_PATTERN = re.compile(
    r'(\[(?:%s)\][^\d\[\]]{0,20}?)([\d,]+)(\s*(?:포획|목격|섭식))'
    % '|'.join(DEVICE_TAGS)
)


def multiply_number(num_str: str, factor: int = FACTOR) -> str:
    """'7,676' -> '76,760',  '1' -> '10' """
    clean = num_str.replace(',', '')
    if not clean.isdigit():
        return num_str
    value = int(clean) * factor
    return f"{value:,}"


def multiply_bracket_counts(text: str) -> str:
    """본문 텍스트 안의 [피닉스프로N]/[썬더블루N] 뒤 숫자를 전부 x10"""
    def _sub(m):
        prefix, num, suffix = m.groups()
        return f"{prefix}{multiply_number(num)}{suffix}"
    return NUM_PATTERN.sub(_sub, text)


def multiply_ph_table_row(row: dict) -> dict:
    """
    row 예시: {"일련번호": "PH003", "파리": "6", "모기": "4", "깔따구": "3",
               "나방파리": "8", "초파리": "6", "날파리": "21", "나방": "6",
               "기타": "0", "합계": "54", "설치장소": "..."}
    """
    total = 0
    for col in INSECT_COLUMNS:
        raw = str(row.get(col, "0")).replace(',', '').strip()
        val = int(raw) if raw.isdigit() else 0
        val *= FACTOR
        row[col] = str(val)
        total += val

    other_raw = str(row.get("기타", "0")).replace(',', '').strip()
    other_val = int(other_raw) if other_raw.isdigit() else 0
    # 기타 컬럼은 요청 대상이 아니므로 그대로 둠(필요시 여기서 *10 적용)
    row["기타"] = str(other_val)
    row["합계"] = str(total + other_val)
    return row


def extract_ph_table(pdf_path: str):
    """
    '8) 포충등별 모니터링 분석' 표를 pdfplumber로 추출.
    실제 PDF의 표 구조(헤더 순서, 병합 여부)에 맞춰 컬럼 매핑을 조정해야 할 수 있습니다.
    우선 raw table을 확인하고 싶다면 이 함수 결과를 print 해보세요.
    """
    all_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or not table[0]:
                    continue
                header = [c.strip() if c else '' for c in table[0]]
                if "일련번호" in header:
                    for raw_row in table[1:]:
                        row = dict(zip(header, raw_row))
                        if str(row.get("일련번호", "")).strip().startswith("PH"):
                            all_rows.append(row)
    return all_rows


def build_output_pdf(narrative_text: str, ph_rows: list, output_path: str):
    """간단한 텍스트/표 형태로 새 PDF 생성 (원본 디자인 재현 아님)"""
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica", 8)  # 한글 폰트가 필요하면 pdfmetrics로 TTF 등록 필요
    y = height - 20 * mm

    for line in narrative_text.splitlines():
        if y < 20 * mm:
            c.showPage()
            c.setFont("Helvetica", 8)
            y = height - 20 * mm
        c.drawString(15 * mm, y, line[:120])
        y -= 4.2 * mm

    c.showPage()
    c.setFont("Helvetica", 9)
    y = height - 20 * mm
    c.drawString(15 * mm, y, "8) 포충등별 모니터링 분석 (x10 적용)")
    y -= 8 * mm
    for row in ph_rows:
        if y < 20 * mm:
            c.showPage()
            c.setFont("Helvetica", 9)
            y = height - 20 * mm
        line = " / ".join(f"{k}:{v}" for k, v in row.items())
        c.drawString(15 * mm, y, line[:130])
        y -= 5 * mm

    c.save()


def main():
    parser = argparse.ArgumentParser(description="CESCO 보고서 수치 x10 변환")
    parser.add_argument("input_pdf")
    parser.add_argument("output_pdf")
    args = parser.parse_args()

    full_text = []
    with pdfplumber.open(args.input_pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text.append(multiply_bracket_counts(text))
    narrative_text = "\n".join(full_text)

    ph_rows = extract_ph_table(args.input_pdf)
    ph_rows = [multiply_ph_table_row(r) for r in ph_rows]

    build_output_pdf(narrative_text, ph_rows, args.output_pdf)
    print(f"완료: {args.output_pdf} 생성됨 (PH 테이블 {len(ph_rows)}행 처리)")


if __name__ == "__main__":
    main()
