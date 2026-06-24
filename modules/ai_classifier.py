"""
AI 분류 모듈 (Google Gemini API 활용)
- ai_classify_batch : 미분류 거래 일괄 분류
- ai_extract_keyword: 저장 시 핵심 키워드 추출
- load_api_key / save_api_key : API 키 영구 저장
"""

import json
import re
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"
_MODEL = "gemini-2.5-pro-preview-05-06"


# ── 키 영구 저장 ──────────────────────────────────────────────

def load_api_key() -> str:
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f).get("anthropic_api_key", "")
        except Exception:
            pass
    return ""


def save_api_key(key: str):
    SETTINGS_PATH.parent.mkdir(exist_ok=True)
    data: dict = {}
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["anthropic_api_key"] = key.strip()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 내부 헬퍼 ────────────────────────────────────────────────

def _get_model(api_key: str):
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(_MODEL)
    except ImportError:
        raise RuntimeError("google-generativeai 패키지가 설치되지 않았습니다. pip install google-generativeai")


def _generate(model, prompt: str) -> str:
    response = model.generate_content(prompt)
    return response.text.strip()


def _parse_json(text: str, default):
    """응답 텍스트에서 JSON 추출"""
    # 마크다운 코드블록 제거
    text = re.sub(r"```(?:json)?", "", text).strip()
    for pat in [r'\[.*\]', r'\{.*\}']:
        m = re.search(pat, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return default


# ── 핵심 키워드 추출 (저장 시) ────────────────────────────────

def ai_extract_keyword(description: str, counterpart: str,
                       branch: str, category: str, api_key: str) -> str:
    """
    수동 저장 시 전체 적요 대신 재사용 가능한 핵심 키워드 추출.
    실패 시 원본 description 반환.
    """
    if not api_key:
        return description
    try:
        model = _get_model(api_key)
        prompt = (
            f"통장 거래 적요에서 다음 달에도 같은 거래를 인식할 수 있는 핵심 키워드를 추출해주세요.\n\n"
            f"적요: {description}\n"
            f"의뢰인/수취인: {counterpart}\n"
            f"분류: {branch} / {category}\n\n"
            f"규칙:\n"
            f"- 날짜(YYYYMMDD, 26xx 등), 순번, 변동 숫자 제외\n"
            f"- 2~10글자의 고정 단어만\n"
            f"- 키워드 단어만 반환 (설명 없이)\n"
            f"예시 입력: '2604국민건강보험' → 예시 출력: 국민건강보험"
        )
        keyword = _generate(model, prompt).split("\n")[0].strip()
        if 2 <= len(keyword) <= 20 and (keyword in description or keyword in counterpart):
            return keyword
    except Exception as e:
        print(f"[AI keyword] {e}")
    return description


# ── 미분류 거래 일괄 AI 분류 ─────────────────────────────────

def ai_classify_batch(transactions: list[dict],
                      branch_list: list[str],
                      category_list: list[str],
                      api_key: str) -> list[dict]:
    """
    ❓미분류 거래 목록을 Gemini에 일괄 전송해 분류 결과 반환.
    반환: [{"id": int, "branch": str, "category": str, "confidence": float}, ...]
    """
    if not api_key or not transactions:
        return []

    results: list[dict] = []
    chunk_size = 40

    for start in range(0, len(transactions), chunk_size):
        chunk = transactions[start:start + chunk_size]
        lines = []
        for i, tx in enumerate(chunk):
            tp  = "입금" if int(tx.get("deposit", 0) or 0) > 0 else "출금"
            amt = int(tx.get("deposit", 0) or 0) or int(tx.get("withdrawal", 0) or 0)
            lines.append(
                f"[{i}] 적요:{tx.get('description','')} | "
                f"의뢰인:{tx.get('counterpart','')} | {tp} {amt:,}원"
            )

        prompt = (
            "당신은 피트니스/골프 시설 운영사(라온스포츠) 회계 분류 전문가입니다.\n\n"
            f"지점 목록: {', '.join(branch_list)}\n"
            f"계정과목 목록: {', '.join(category_list)}\n\n"
            "아래 통장 거래를 분류해주세요.\n\n"
            "분류 규칙:\n"
            "- KB·NH·BC·SHC·하나·국민·우리 등 카드사 코드 입금 → category: '제외'\n"
            "- '라온스포츠' 관련 입출금, 자금대체 → category: '제외'\n"
            "- 지점을 특정할 수 없으면 branch: ''\n"
            "- confidence: 확신도 0.0~1.0\n\n"
            "거래 목록:\n" + "\n".join(lines) + "\n\n"
            "JSON 배열만 반환 (다른 텍스트, 마크다운 없이):\n"
            '[{"id":0,"branch":"지점명","category":"계정과목","confidence":0.9}]'
        )

        try:
            model = _get_model(api_key)
            text  = _generate(model, prompt)
            parsed = _parse_json(text, [])
            if isinstance(parsed, list):
                for item in parsed:
                    item["id"] = item.get("id", 0) + start
                results.extend(parsed)
        except Exception as e:
            print(f"[AI batch] chunk {start}: {e}")

    return results
