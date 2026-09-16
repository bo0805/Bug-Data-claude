"""
CESCO 서비스 결과 보고서 PDF의 특정 해충 포획 수치를 x10 배로 변환하되,
원본 레이아웃(글자 위치, 표, 로고 등)은 그대로 유지하는 스크립트.

PyMuPDF(fitz)의 redaction 기능을 사용해 원래 숫자가 있던 자리를 지우고
그 자리에 x10된 숫자를 다시 그려 넣는 방식입니다.

변환 대상
1. "[피닉스프로N]" / "[썬더블루N]" 태그가 포함된 문단(block) 안의 순수 숫자 토큰 -> x10
   (곤충명, 서비스일자, 위치명 등 숫자+한글이 섞인 토큰은 건드리지 않음)
2. 일련번호가 "PH"로 시작하는 행(포충등별 모니터링 분석 표)
   -> 파리, 모기, 깔따구, 나방파리, 초파리, 날파리, 나방 (앞 7개 숫자 컬럼) x10
   -> 기타(8번째)는 그대로, 합계(9번째)는 x10된 값들의 합으로 재계산

설치:
    pip install PyMuPDF

사용법:
    python multiply_pest_report_fitz.py input.pdf output.pdf

주의사항 (반드시 확인하세요)
- 새 숫자가 원래보다 자릿수가 늘어나면(예: 54 -> 540) 원래 칸 폭을 넘어가
  옆 칸 글자와 겹칠 수 있습니다. 표 컬럼 폭이 좁다면 출력 결과를 육안으로 검수하세요.
- 폰트 크기는 원래 글자 높이(bbox)를 기준으로 추정한 값이라 완벽히 동일하지 않을 수 있습니다.
- "PH + 숫자" 뒤에 숫자 토큰이 정확히 9개(파리/모기/깔따구/나방파리/초파리/날파리/나방/기타/합계)
  나온다고 가정합니다. 실제 표에서 이 순서/개수가 다르면 해당 행은 건너뛰고 경고를 출력합니다.
- 원본 파일은 항상 백업해두고, 결과 PDF를 몇 페이지 직접 대조해보는 것을 권장합니다.
"""

import re
import sys

import fitz  # PyMuPDF

FACTOR = 10
DEVICE_TAGS = ("피닉스프로N", "썬더블루N")

PURE_NUM_RE = re.compile(r'^[\d,]+$')
PH_CODE_RE = re.compile(r'^PH\d+$')

INSECT_COL_NAMES = ["파리", "모기", "깔따구", "나방파리", "초파리", "날파리", "나방"]  # 앞 7개, x10 대상
# 표 컬럼 순서: [파리, 모기, 깔따구, 나방파리, 초파리, 날파리, 나방, 기타, 합계]


def multiply_str(num_str: str, factor: int = FACTOR) -> str:
    clean = num_str.replace(',', '')
    val = int(clean) * factor
    return f"{val:,}"


def group_words_by_key(words, key_fn):
    groups = {}
    for w in words:
        groups.setdefault(key_fn(w), []).append(w)
    for k in groups:
        groups[k].sort(key=lambda w: w[0])  # x0 기준 좌->우 정렬
    return groups


def collect_targets(page):
    """
    (bbox, new_text) 리스트 반환.
    words 튜플 구조: (x0, y0, x1, y1, text, block_no, line_no, word_no)
    """
    words = page.get_text("words")
    if not words:
        return []

    blocks = group_words_by_key(words, key_fn=lambda w: w[5])
    lines = group_words_by_key(words, key_fn=lambda w: (w[5], w[6]))

    targets = []

    # 1) 피닉스프로N / 썬더블루N 문단 처리
    for block_no, block_words in blocks.items():
        block_text = " ".join(w[4] for w in block_words)
        if any(tag in block_text for tag in DEVICE_TAGS):
            for w in block_words:
                token = w[4]
                if PURE_NUM_RE.match(token):
                    bbox = fitz.Rect(w[0], w[1], w[2], w[3])
                    targets.append((bbox, multiply_str(token)))

    # 2) PH0xx 표 행 처리
    for key, line_words in lines.items():
        if not line_words:
            continue
        first_token = line_words[0][4]
        if not PH_CODE_RE.match(first_token):
            continue

        numeric_tokens = [w for w in line_words if PURE_NUM_RE.match(w[4])]
        if len(numeric_tokens) < 9:
            print(f"[경고] {first_token}: 숫자 컬럼이 9개 미만이라 건너뜀 "
                  f"({len(numeric_tokens)}개 발견)")
            continue

        cols = numeric_tokens[:9]
        values = [int(w[4].replace(',', '')) for w in cols]

        new_values = values[:]
        for i in range(7):  # 파리~나방
            new_values[i] = values[i] * FACTOR
        # 기타(index 7)는 그대로, 합계(index 8) 재계산
        new_values[8] = sum(new_values[:7]) + new_values[7]

        for w, new_v in zip(cols, new_values):
            bbox = fitz.Rect(w[0], w[1], w[2], w[3])
            targets.append((bbox, f"{new_v:,}"))

    return targets


def apply_targets(page, targets):
    if not targets:
        return

    for bbox, _new_text in targets:
        page.add_redact_annot(bbox, fill=(1, 1, 1))
    page.apply_redactions()

    for bbox, new_text in targets:
        fontsize = max(bbox.height * 0.72, 6)
        page.insert_text(
            (bbox.x0, bbox.y1 - 1),
            new_text,
            fontsize=fontsize,
            fontname="helv",
            color=(0, 0, 0),
        )


def main():
    if len(sys.argv) != 3:
        print("사용법: python multiply_pest_report_fitz.py input.pdf output.pdf")
        sys.exit(1)

    input_pdf, output_pdf = sys.argv[1], sys.argv[2]
    doc = fitz.open(input_pdf)

    total_changed = 0
    for page_index, page in enumerate(doc):
        targets = collect_targets(page)
        apply_targets(page, targets)
        total_changed += len(targets)
        if targets:
            print(f"페이지 {page_index + 1}: {len(targets)}개 수치 변경")

    doc.save(output_pdf)
    print(f"완료: '{output_pdf}' 저장됨 (총 {total_changed}개 수치 x{FACTOR} 적용)")


if __name__ == "__main__":
    main()
