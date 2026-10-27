import os
import io
import csv
import re
import json
import time
import inspect
import logging
import pandas as pd
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

# Google Gemini API 최신 SDK
from google import genai
from google.genai import types

# 12개 분석 도구 모듈 임포트
import tools

# .env 환경변수 로드
load_dotenv()

# 백엔드 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ChannelAnalyzer")

app = Flask(__name__)

# 업로드 최대 용량 설정 (기본 10MB)
max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "10"))
app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

# 환경변수 읽기
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# 기본 디렉터리 및 raw_data 폴더 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(BASE_DIR, "raw_data")
os.makedirs(RAW_DATA_DIR, exist_ok=True)

# 메모리 기반 단일 데이터셋 보관소 (디스크 영구 저장 배제)
CURRENT_DATASET = {
    "file_name": None,
    "file_size": 0,
    "encoding": None,
    "skipped_rows": 0,
    "raw_df": None,
    "clean_df": None,
    "metadata": None,
    "last_result": None  # 최근 /run 계산 결과 캐시 (POST /explain 연동용)
}

def detect_encoding_and_header(file_bytes):
    """
    1) utf-8-sig, utf-8, cp949, euc-kr 순으로 인코딩 자동 탐지
    2) 상단 주석/출처를 스캔하여 KOSIS 실제 헤더 행 위치 자동 탐지 (열 개수 2개 이상 및 키워드 복합 판정)
    """
    encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    decoded_text = None
    used_encoding = None

    for enc in encodings:
        try:
            decoded_text = file_bytes.decode(enc)
            used_encoding = enc
            logger.info(f"[CSV] 인코딩 시도 성공: {enc}")
            break
        except UnicodeDecodeError:
            logger.info(f"[CSV] 인코딩 시도 실패: {enc}, 다음 인코딩 시도")
            continue

    if decoded_text is None:
        raise ValueError("지원하는 인코딩(utf-8-sig, utf-8, cp949, euc-kr)으로 파일을 디코딩할 수 없습니다.")

    reader = csv.reader(io.StringIO(decoded_text))
    keywords = ["상품군", "운영형태", "시점", "판매매체", "카테고리", "거래액", "판매액", "구분"]
    meta_prefixes = ["통계표명", "조회조건", "출처", "단위", "작성부서", "자료갱신", "주:"]

    best_match_idx = 0
    max_score = -1

    rows = []
    for idx, row in enumerate(reader):
        if idx >= 30:
            break
        rows.append(row)

    for idx, row in enumerate(rows):
        if not row or len(row) < 2:
            continue

        first_cell = str(row[0]).strip()
        second_cell = str(row[1]).strip() if len(row) > 1 else ""

        # KOSIS 상단 통계표 메타데이터 주석 행 건너뛰기
        if any(first_cell.startswith(p) for p in meta_prefixes) or any(second_cell.startswith(p) for p in meta_prefixes):
            continue

        matches = sum(1 for kw in keywords if any(kw in str(cell) for cell in row))
        col_count = len(row)
        score = (matches * 10) + col_count

        if matches >= 1 and score > max_score:
            max_score = score
            best_match_idx = idx

    header_row_idx = best_match_idx
    logger.info(f"[CSV] 헤더 행 탐지 성공: 제 {header_row_idx + 1}행 (상단 건너뛴 줄 수: {header_row_idx})")

    return decoded_text, used_encoding, header_row_idx

def analyze_kosis_dataset(df):
    """
    KOSIS 데이터셋 정밀 진단:
    - 상품군, 운영형태, 시점, 거래액 열 식별 (Wide/Long 형태 대응)
    - 합계/소계 행 분리 및 필터링
    - 수치 결측치 정제 및 이상치 탐지
    - 11가지 진단 메타데이터 구성
    """
    warnings = []

    # 0. KOSIS 하단 통계 주석 및 출처 행 선제적 필터링 (예: "주: ...", "출처: ...", "자료: ...")
    note_prefixes = ("주:", "주 :", "출처:", "출처 :", "자료:", "※", "*", "참고:")
    if len(df.columns) > 0:
        first_col = df.columns[0]
        note_mask = df[first_col].astype(str).str.strip().str.startswith(note_prefixes)
        if note_mask.sum() > 0:
            logger.info(f"[CLEAN] 하단 통계 주석/출처 {note_mask.sum()}개 행 제거")
            df = df[~note_mask].copy()

    cols = list(df.columns)

    cat_col = None
    op_col = None
    time_col = None
    val_col = None

    # 1. 상품군(카테고리) 열 탐색 (다중 계층 컬럼 대응: 예: 상품군별(1), 상품군별(2))
    cat_candidates = [c for c in cols if any(k in str(c).strip() for k in ["상품군", "카테고리", "품목"])]
    if cat_candidates:
        if len(cat_candidates) == 1:
            cat_col = cat_candidates[0]
        else:
            best_cat = cat_candidates[-1]
            max_unique = -1
            for cand in cat_candidates:
                vals = df[cand].dropna().astype(str).str.strip()
                non_agg = vals[~vals.isin(["합계", "총계", "소계", "계", "전체"])]
                cnt = non_agg.nunique()
                if cnt >= max_unique:
                    max_unique = cnt
                    best_cat = cand
            cat_col = best_cat

    # 2. 운영형태(채널) 열 탐색 (다중 계층 컬럼 대응: 예: 운영형태별(1), 운영형태별(2))
    op_candidates = [c for c in cols if any(k in str(c).strip() for k in ["운영형태", "판매매체", "채널", "매체별"])]
    if op_candidates:
        if len(op_candidates) == 1:
            op_col = op_candidates[0]
        else:
            best_op = op_candidates[-1]
            for cand in op_candidates:
                cand_vals = " ".join(df[cand].dropna().astype(str).unique())
                if "온라인몰" in cand_vals or "병행" in cand_vals:
                    best_op = cand
                    break
            op_col = best_op

    # 3. 시점 및 거래액 열 탐색 (Long format에 이미 존재하는 경우)
    for c in cols:
        c_clean = str(c).strip()
        if not time_col and any(k in c_clean for k in ["시점", "연월", "기간", "날짜"]):
            time_col = c
        elif not val_col and any(k in c_clean for k in ["거래액", "판매액", "데이터", "금액", "수치"]):
            val_col = c

    # 4. Wide format (피벗 형태) 감지 및 Long format 변환
    if cat_col and op_col and (not time_col or not val_col):
        id_vars = [cat_col, op_col]
        potential_time_cols = [c for c in cols if c not in id_vars]
        # 4자리 연도로 시작하는 시점 컬럼 탐색 (예: 2023.01, 2024.10 p), 2023 1/4 등)
        year_pattern_cols = [c for c in potential_time_cols if re.match(r'^\d{4}', str(c).strip())]
        if len(year_pattern_cols) >= 2:
            logger.info(f"[CLEAN] Wide format 감지: {len(year_pattern_cols)}개 시점 열을 Long format으로 정규화 변환합니다.")
            df = pd.melt(df, id_vars=id_vars, value_vars=year_pattern_cols, var_name="시점", value_name="거래액")
            # 시점 문자열에서 잠정치 'p)', '(p)' 및 공백 제거하여 정규화 (예: '2024.10 p)' -> '2024.10')
            df["시점"] = df["시점"].astype(str).str.strip().str.replace(r'[\s\(\)pP]', '', regex=True)
            time_col = "시점"
            val_col = "거래액"
            warnings.append("피벗(Wide) 형태로 나열된 시점 열들을 분석용 표준 목록 형태로 자동 변환하였습니다.")

    if not cat_col:
        raise ValueError("상품군(카테고리) 열을 감지할 수 없습니다. 컬럼명을 확인해주세요.")
    if not op_col:
        raise ValueError("운영형태(판매매체) 열을 감지할 수 없습니다. '온라인몰', '온·오프라인 병행몰' 등의 열이 필요합니다.")
    if not time_col:
        raise ValueError("시점(연월) 열을 감지할 수 없습니다. 시점 컬럼을 포함해주세요.")
    if not val_col:
        raise ValueError("거래액(판매액) 열을 감지할 수 없습니다. 거래액 수치 컬럼을 포함해주세요.")

    unit = "백만원"
    if "억원" in str(val_col):
        unit = "억원"
    elif "천원" in str(val_col):
        unit = "천원"
    elif "원" in str(val_col) and "백만원" not in str(val_col):
        unit = "원"

    # 5. 수치 결측치 및 천단위 콤마, 잠정치 기호 정제
    raw_vals = (
        df[val_col].astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace(r'[pP\)]', '', regex=True)
        .str.strip()
    )
    missing_mask = raw_vals.isin(["-", "", "...", "nan", "NaN", "None", "무응답", "null"])
    missing_count = int(missing_mask.sum())

    cleaned_series = pd.to_numeric(raw_vals.replace({"-": "0", "...": "0", "무응답": "0", "": "0"}), errors="coerce").fillna(0.0)
    df[val_col] = cleaned_series

    # 6. 추가적인 빈 행 및 잔여 주석 행 필터링
    clean_cat_mask = (
        df[cat_col].isna() |
        (df[cat_col].astype(str).str.strip() == "") |
        df[cat_col].astype(str).str.strip().str.startswith(note_prefixes)
    )
    if clean_cat_mask.sum() > 0:
        df = df[~clean_cat_mask].copy()

    if missing_count > 0:
        warnings.append(f"결측치 또는 하이픈('-')으로 표기된 데이터 {missing_count}건을 0으로 안전하게 보정하였습니다.")
        logger.info(f"[CLEAN] 결측치/하이픈 {missing_count}건을 0으로 치환 완료")

    aggregate_keywords = ["합계", "총계", "소계", "계", "전체"]
    cat_agg_mask = (
        df[cat_col].astype(str).str.strip().isin(aggregate_keywords) |
        df[cat_col].astype(str).str.contains(r"^합계|^총계|\(계\)", regex=True)
    )
    op_agg_mask = df[op_col].astype(str).str.strip().isin(aggregate_keywords)
    total_agg_mask = cat_agg_mask | op_agg_mask
    agg_rows_count = int(total_agg_mask.sum())

    if agg_rows_count > 0:
        warnings.append(f"이중 계산 방지를 위해 '합계/계' 항목({agg_rows_count}개 행)을 기본 분석에서 자동 분리 필터링했습니다.")
        logger.info(f"[CLEAN] '합계/계' 행 분리: {agg_rows_count}건 감지 및 격리 완료")

    clean_df = df[~total_agg_mask].copy()

    all_categories = sorted([str(x).strip() for x in df[cat_col].dropna().unique()])
    normal_categories = sorted([str(x).strip() for x in clean_df[cat_col].dropna().unique()])
    aggregate_categories = [c for c in all_categories if c not in normal_categories]

    all_operations = sorted([str(x).strip() for x in df[op_col].dropna().unique()])
    normal_operations = sorted([str(x).strip() for x in clean_df[op_col].dropna().unique()])

    periods = sorted([str(x).strip() for x in df[time_col].dropna().unique()])
    start_period = periods[0] if periods else ""
    end_period = periods[-1] if periods else ""
    recommended_period = end_period

    zero_count = int((clean_df[val_col] == 0).sum())
    total_clean_rows = len(clean_df)
    preview_rows = clean_df.head(10).to_dict(orient="records")

    metadata = {
        "detected_columns": {
            "category_col": cat_col,
            "operation_col": op_col,
            "period_col": time_col,
            "volume_col": val_col,
            "unit": unit
        },
        "operations": {
            "all_list": all_operations,
            "analyzable_list": normal_operations
        },
        "categories": {
            "total_count": len(normal_categories),
            "analyzable_list": normal_categories,
            "aggregate_list": aggregate_categories
        },
        "periods": {
            "start": start_period,
            "end": end_period,
            "total_count": len(periods),
            "all_list": periods,
            "recommended": recommended_period
        },
        "summary": {
            "total_raw_rows": len(df),
            "total_clean_rows": total_clean_rows,
            "aggregate_rows_count": agg_rows_count,
            "missing_count": missing_count,
            "zero_count": zero_count
        },
        "warnings": warnings,
        "preview_rows": preview_rows
    }

    return df, clean_df, metadata

def _get_fallback_suggestions(meta):
    rec_period = meta.get("periods", {}).get("recommended", "")
    all_periods = meta.get("periods", {}).get("all_list", [])

    has_multi_periods = len(all_periods) >= 2

    suggestions = [
        {
            "tool": "channel_share_by_category",
            "params": {"reference_period": rec_period, "exclude_aggregates": True},
            "reference_period": rec_period,
            "why": f"가장 최근 시점({rec_period}) 기준 소비자들이 어떤 품목을 순수 온라인몰에서 사고 어디서 온·오프라인 병행몰을 선호하는지 전체 점유율을 100% 누적 막대로 즉시 파악할 수 있습니다.",
            "caution": "합계(총계) 행을 반드시 제외해야 각 상품군별 점유율의 합이 100%로 정확히 산출됩니다."
        },
        {
            "tool": "omnichannel_dominance_top_n",
            "params": {"reference_period": rec_period, "top_n": 5, "exclude_aggregates": True},
            "reference_period": rec_period,
            "why": "순수 온라인몰이 압도하기 어려운, 백화점/대형마트 등 오프라인 매장 연계 병행몰 점유율이 가장 높은 품목(신선식품, 명품/패션 등)을 발굴합니다.",
            "caution": "표본 거래액이 너무 작은 상품군은 점유율 착시가 발생할 수 있으므로 거래 규모와 함께 확인해야 합니다."
        },
        {
            "tool": "macro_channel_ratio",
            "params": {"reference_period": rec_period, "exclude_aggregates": True},
            "reference_period": rec_period,
            "why": f"선택 시점({rec_period}) 전체 이커머스 거래액 중 온라인몰과 병행몰의 거시적 총 비중(%)을 도넛 차트로 한눈에 파악합니다.",
            "caution": "단일 상품군이 아닌 전체 이커머스 시장 전체를 조망하는 거시적 지표입니다."
        }
    ]

    if has_multi_periods:
        base_p = all_periods[0]
        suggestions.append({
            "tool": "channel_share_shift",
            "params": {"base_period": base_p, "target_period": rec_period, "exclude_aggregates": True},
            "reference_period": f"{base_p} vs {rec_period}",
            "why": f"{base_p} 대비 {rec_period} 동안 소비자들이 병행몰에서 온라인몰로, 혹은 온라인몰에서 병행몰로 이동한 점유율 변화폭(%p)을 추적합니다.",
            "caution": "두 시점 모두에 동일하게 집계된 공통 상품군만을 대상으로 변화폭을 산출합니다."
        })
    else:
        suggestions.append({
            "tool": "channel_dominance_matrix",
            "params": {"reference_period": rec_period, "exclude_aggregates": True},
            "reference_period": rec_period,
            "why": "각 상품군의 전체 거래 규모(X축) 대비 온라인몰 점유율(Y축)을 4사분면으로 매핑하여 대형 주력 시장과 틈새 특화 시장을 시각적으로 구분합니다.",
            "caution": "거래 규모 중간값(Median)을 기준으로 사분면이 자동 분류됩니다."
        })

    return suggestions

def _generate_fallback_explain_report(mode, result, meta):
    ref_period = result.get("reference_period", "")
    unit = result.get("unit", "백만원")
    t_data = result.get("table_data", [])

    if mode == "A":
        return f"""> [!WARNING] **모드 A (비교용, 허술한 모드)**: 정밀 Pandas 계산 결과 없이 단순 메타데이터만으로 AI가 자의적 추정을 시도한 결과입니다.

소비자들은 일반적으로 생필품이나 공산품은 쿠팡 등 **순수 온라인몰**에서 더 많이 구매하고, 백화점 브랜드 의류나 신선도가 중요한 식품은 **온·오프라인 병행몰**을 많이 이용하는 경향이 있습니다.

*(주의: 위 내용은 실제 수치 집계 없이 작성된 추정이므로 비즈니스 의사결정에 그대로 사용할 수 없습니다.)*
"""

    online_strong = []
    omni_strong = []
    key_numbers_lines = []

    for idx, r in enumerate(t_data[:5], 1):
        if "pure_online_share_pct" in r:
            on_pct = r["pure_online_share_pct"]
            om_pct = r["omnichannel_share_pct"]
            cat = r.get("category", "")
            key_numbers_lines.append(f"- **{cat}**: 온라인몰 {on_pct}% vs 온·오프라인 병행몰 {om_pct}% (총 {r.get('total_volume', 0):,.0f} {unit})")
            if on_pct >= 50.0:
                online_strong.append(f"{cat}({on_pct}%)")
            else:
                omni_strong.append(f"{cat}({om_pct}%)")

    return f"""## 분석 개요 및 기준 시점
- **분석 기준 시점**: {ref_period}
- **통계 단위**: 거래액({unit}), 점유율(%)
- **분석 도구**: {result.get('tool_title', '채널 비교 분석')} (합계/계 이중 계산 행 사전 필터링 완료)

## 핵심 수치 요약 (Key Numbers)
{chr(10).join(key_numbers_lines) if key_numbers_lines else "- 집계된 주요 품목 수치가 요약되었습니다."}

## 상품군별 채널 지배력 분석 (온라인몰 강세 vs 병행몰 강세)
- **순수 온라인몰 우세 상품군**: {', '.join(online_strong) if online_strong else '없음'}
- **온·오프라인 병행몰 우세 상품군**: {', '.join(omni_strong) if omni_strong else '없음'}

## 채널 선호도 차이의 주요 원인 및 소비자 행동 해석
1. **규격화 및 가격 비교 용이성**: 사양과 규격이 명확한 공산품 및 디지털 기기는 최저가 검색과 빠른 로켓배송을 제공하는 순수 온라인 전용몰로 소비가 집중되는 경향을 보입니다.
2. **체험 및 신뢰도/신선도 중요성**: 피팅이 중요한 고가 의류나 신선도가 직결되는 식료품은 오프라인 매장의 품질 신뢰도와 유통망을 보유한 온·오프라인 병행몰(백화점몰/마트몰)에 대한 소비자 선호도가 상대적으로 높게 유지됩니다.

## 데이터의 한계 및 추가 확인이 필요한 사항
- 본 통계는 KOSIS에서 제공하는 거래액 총량 지표를 기반으로 하므로, 개별 소비자 단위의 구매 빈도나 객단가, 반품률 등 미시적 행동 요인은 이 데이터만으로 확인할 수 없습니다.
- 외부 프로모션(예: 연말 할인 페스티벌, 라이브 커머스 특가 등) 효과는 가설로만 유추 가능하며, 향후 상세 고객 행동 로그와의 결합 분석이 권장됩니다.
"""

@app.before_request
def log_request_info():
    """모든 요청 진입 시 백엔드 로그 기록"""
    logger.info(f"[REQUEST] {request.method} {request.path} - Remote: {request.remote_addr}")

@app.route("/")
def index():
    """메인 대시보드 페이지"""
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    """서버 상태 및 API 키 설정 여부 반환 (키 값 자체는 철저히 은닉)"""
    is_key_set = bool(GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here")
    return jsonify({
        "status": "ok",
        "gemini_model": GEMINI_MODEL,
        "api_key_configured": is_key_set,
        "max_upload_mb": max_upload_mb,
        "message": "서버가 정상적으로 구동 중입니다."
    }), 200

def _process_and_store_dataset(file_bytes, file_name, file_size):
    """CSV 바이트 데이터를 정밀 디코딩 및 분석하여 CURRENT_DATASET에 캐싱하고 진단 메타데이터 반환"""
    decoded_text, used_encoding, header_row_idx = detect_encoding_and_header(file_bytes)

    df = pd.read_csv(
        io.StringIO(decoded_text),
        skiprows=header_row_idx,
        dtype=str
    )
    df.columns = [str(col).strip().replace("\n", " ") for col in df.columns]

    raw_df, clean_df, metadata = analyze_kosis_dataset(df)

    CURRENT_DATASET["file_name"] = file_name
    CURRENT_DATASET["file_size"] = file_size
    CURRENT_DATASET["encoding"] = used_encoding
    CURRENT_DATASET["skipped_rows"] = header_row_idx
    CURRENT_DATASET["raw_df"] = raw_df
    CURRENT_DATASET["clean_df"] = clean_df
    CURRENT_DATASET["metadata"] = metadata
    CURRENT_DATASET["last_result"] = None

    logger.info(f"[CSV] 정밀 진단 완료: {file_name} (상품군: {metadata['categories']['total_count']}개, 운영형태: {len(metadata['operations']['analyzable_list'])}개, 시점: {metadata['periods']['total_count']}개)")

    return {
        "status": "success",
        "file_info": {
            "file_name": file_name,
            "file_size_bytes": file_size,
            "file_size_formatted": f"{round(file_size / 1024, 2)} KB"
        },
        "encoding_info": {
            "detected_encoding": used_encoding,
            "skipped_rows": header_row_idx
        },
        "dimension_info": {
            "raw_rows": metadata["summary"]["total_raw_rows"],
            "clean_rows": metadata["summary"]["total_clean_rows"],
            "columns_count": len(raw_df.columns)
        },
        "detected_columns": metadata["detected_columns"],
        "operation_types": metadata["operations"],
        "categories": metadata["categories"],
        "periods": metadata["periods"],
        "recommended_period": metadata["periods"]["recommended"],
        "missing_outliers_summary": {
            "missing_count": metadata["summary"]["missing_count"],
            "zero_count": metadata["summary"]["zero_count"],
            "aggregate_rows_count": metadata["summary"]["aggregate_rows_count"]
        },
        "preview_rows": metadata["preview_rows"],
        "warnings": metadata["warnings"],
        "message": f"KOSIS 데이터 진단이 성공적으로 완료되었습니다 ({file_name})."
    }

@app.route("/inspect", methods=["POST"])
def inspect_dataset():
    """Step 13: 사용자가 웹에서 업로드한 CSV 파일 정밀 진단"""
    if "file" not in request.files:
        logger.error("[ERROR] 업로드 요청에 file 필드가 누락되었습니다.")
        return jsonify({"status": "error", "message": "업로드할 CSV 파일을 선택해주세요."}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        logger.error("[ERROR] 파일이 선택되지 않았습니다.")
        return jsonify({"status": "error", "message": "파일이 선택되지 않았습니다."}), 400

    if not file.filename.lower().endswith(".csv"):
        logger.error(f"[ERROR] 비허용 확장자: {file.filename}")
        return jsonify({"status": "error", "message": ".csv 파일만 업로드할 수 있습니다."}), 400

    file_bytes = file.read()
    file_size = len(file_bytes)
    if file_size == 0:
        logger.error("[ERROR] 업로드된 파일이 빈 파일입니다.")
        return jsonify({"status": "error", "message": "업로드된 CSV 파일의 내용이 비어있습니다."}), 400

    try:
        diag_result = _process_and_store_dataset(file_bytes, file.filename, file_size)
        return jsonify(diag_result), 200
    except Exception as e:
        logger.error(f"[ERROR] CSV 정밀 진단 실패: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"CSV 파일 진단 중 오류가 발생했습니다: {str(e)}"}), 500

@app.route("/api/raw-files", methods=["GET"])
def get_raw_files():
    """신규 추가: raw_data/ 폴더 내 분석 가능한 CSV 원본 파일 목록 반환"""
    try:
        files = []
        if os.path.exists(RAW_DATA_DIR):
            for fname in sorted(os.listdir(RAW_DATA_DIR)):
                if fname.lower().endswith(".csv"):
                    fpath = os.path.join(RAW_DATA_DIR, fname)
                    stat = os.stat(fpath)
                    files.append({
                        "name": fname,
                        "size_bytes": stat.st_size,
                        "size_formatted": f"{round(stat.st_size / 1024, 2)} KB",
                        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                    })
        return jsonify({
            "status": "success",
            "folder": "raw_data",
            "files": files,
            "count": len(files)
        }), 200
    except Exception as e:
        logger.error(f"[ERROR] raw_data 목록 조회 실패: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/inspect-from-folder", methods=["POST"])
def inspect_from_folder():
    """신규 추가: raw_data/ 폴더에 위치한 CSV 원본 파일을 직접 열어 즉시 진단 수행"""
    req_data = request.get_json(silent=True) or {}
    file_name = str(req_data.get("file_name", "")).strip()

    if not file_name:
        csv_files = [f for f in os.listdir(RAW_DATA_DIR) if f.lower().endswith(".csv")]
        if not csv_files:
            return jsonify({
                "status": "error",
                "message": "raw_data 폴더에 CSV 파일이 없습니다. 먼저 raw_data 폴더에 CSV 파일을 넣어주세요."
            }), 404
        csv_files.sort(key=lambda f: os.path.getmtime(os.path.join(RAW_DATA_DIR, f)), reverse=True)
        file_name = csv_files[0]

    safe_name = os.path.basename(file_name)
    file_path = os.path.join(RAW_DATA_DIR, safe_name)

    if not os.path.isfile(file_path):
        return jsonify({
            "status": "error",
            "message": f"지정된 파일을 찾을 수 없습니다: raw_data/{safe_name}"
        }), 404

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_size = len(file_bytes)
        if file_size == 0:
            return jsonify({
                "status": "error",
                "message": f"raw_data/{safe_name} 파일 내용이 비어있습니다."
            }), 400

        diag_result = _process_and_store_dataset(file_bytes, f"raw_data/{safe_name}", file_size)
        return jsonify(diag_result), 200
    except Exception as e:
        logger.error(f"[ERROR] raw_data/{safe_name} 진단 실패: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"raw_data/{safe_name} 진단 중 오류 발생: {str(e)}"}), 500

@app.route("/suggest", methods=["POST"])
def suggest_tools():
    """Step 17: KOSIS 진단 메타데이터를 기반으로 Gemini API가 최적의 분석 도구 3~5개를 JSON으로 제안"""
    meta = CURRENT_DATASET.get("metadata")
    if not meta:
        logger.error("[ERROR] 업로드 및 진단된 데이터셋이 없습니다.")
        return jsonify({"status": "error", "message": "먼저 CSV 파일을 업로드하여 진단을 완료해주세요."}), 400

    cats = meta["categories"]["analyzable_list"]
    ops = meta["operations"]["analyzable_list"]
    periods = meta["periods"]["all_list"]
    rec_period = meta["periods"]["recommended"]
    unit = meta["detected_columns"]["unit"]

    catalog_description = """
[사용 가능한 도구 카탈로그 (오직 아래 12개 도구명만 사용 가능)]
1. channel_share_by_category : 기준 시점 상품군별 온라인몰 vs 병행몰 점유율(%) (100% 누적 막대 차트)
2. pure_online_dominance_top_n : 온라인 전용몰 점유율이 가장 높은 상위 N개 상품군 (수평 막대 차트)
3. omnichannel_dominance_top_n : 온·오프라인 병행몰 점유율이 가장 높은 상위 N개 상품군 (수평 막대 차트)
4. macro_channel_ratio : 선택 시점 전체 거래액 중 온라인몰 vs 병행몰 총 비중 (도넛 차트)
5. category_channel_trend : 특정 상품군의 시계열(월별) 운영형태별 거래액 추이 (다중 선 차트)
6. channel_share_shift : 두 시점 간 상품군별 병행몰 점유율 변화폭(%p) (발산 막대 차트)
7. total_volume_ranking : 기준 시점 전체 거래액 상위 상품군 순위 및 채널 구성 (누적 막대 차트)
8. growth_rate_by_channel : 기간 동안 온라인몰과 병행몰의 상품군별 거래액 성장률(%) 비교 (그룹 막대 차트)
9. channel_dominance_matrix : 상품군별 거래규모(X축) 대비 온라인몰 점유율(Y축) 사분면 분류 (산점도)
10. channel_basket_composition : 온라인몰 내 구성비 vs 병행몰 내 구성비 비교 (그룹 막대)
11. seasonal_channel_pattern : 특정 상품군의 채널 선호 월별 계절성 분석 (평균 선 차트)
12. single_category_deep_dive : 선택한 1개 상품군의 거래 규모, 채널 점유율, 시장 순위 종합 진단 대시보드
"""

    prompt = f"""
당신은 대한민국 이커머스 유통 채널(온라인몰 vs 온·오프라인 병행몰) 전문 분석 컨설턴트입니다.
업로드된 KOSIS 통계청 데이터셋의 메타데이터 진단 결과를 바탕으로, 사용자에게 가장 인사이트가 풍부한 최적의 분석 도구 3~5개를 추천해 주십시오.

{catalog_description}

[업로드된 데이터셋 진단 정보]
- 포함된 상품군 수: {len(cats)}개 ({', '.join(cats[:8])}{' 외 ' + str(len(cats)-8) + '개' if len(cats) > 8 else ''})
- 감지된 운영형태 채널: {', '.join(ops)}
- 시점 범위: {periods[0] if periods else ''} ~ {periods[-1] if periods else ''} (총 {len(periods)}개 시점)
- 권장 기준 시점: {rec_period}
- 데이터 단위: {unit}

[작성 및 출력 절대 규칙]
1. 반드시 도구 카탈로그에 존재하는 12개 영문 도구명 중 3~5개를 엄선하십시오.
2. 만약 시점이 1개뿐이라면 시계열 도구(channel_share_shift, growth_rate_by_channel 등)는 피하고 단면 분석 도구를 추천하십시오.
3. 결과는 오직 유효한 순수 JSON 객체 포맷으로만 출력하십시오 (마크다운 백틱 없이 순수 JSON 문자열).

JSON 출력 규격:
{{
  "suggestions": [
    {{
      "tool": "도구명",
      "params": {{"reference_period": "{rec_period}", "exclude_aggregates": true}},
      "reference_period": "{rec_period}",
      "why": "이 도구를 추천하는 구체적인 비즈니스 분석 이유",
      "caution": "해석 시 소비자가 유의해야 할 점 (예: 이중계산 주의 등)"
    }}
  ]
}}
"""
    start_ai_time = time.time()

    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        logger.info("[AI] Gemini API Key 미설정: 규칙 기반 스마트 권장 도구 반환")
        suggestions = _get_fallback_suggestions(meta)
        return jsonify({
            "status": "success",
            "source": "rule_based_fallback",
            "suggestions": suggestions,
            "message": "Gemini API 키가 아직 설정되지 않아 데이터셋 기반 권장 분석 도구를 제안합니다."
        }), 200

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )

        ai_elapsed = round(time.time() - start_ai_time, 3)
        raw_content = response.text.strip()
        logger.info(f"[AI] Gemini 제안 수신 완료 (소요시간: {ai_elapsed}s, 모델: {GEMINI_MODEL})")

        cleaned_json_str = re.sub(r"^```json\s*", "", raw_content)
        cleaned_json_str = re.sub(r"\s*```$", "", cleaned_json_str).strip()

        suggest_data = json.loads(cleaned_json_str)
        suggestions = suggest_data.get("suggestions", [])

        valid_tool_names = [
            "channel_share_by_category", "pure_online_dominance_top_n", "omnichannel_dominance_top_n",
            "macro_channel_ratio", "category_channel_trend", "channel_share_shift",
            "total_volume_ranking", "growth_rate_by_channel", "channel_dominance_matrix",
            "channel_basket_composition", "seasonal_channel_pattern", "single_category_deep_dive",
            "period_category_channel_trend", "period_product_channel_behavior"
        ]
        validated_suggestions = [s for s in suggestions if s.get("tool") in valid_tool_names]

        if not validated_suggestions:
            validated_suggestions = _get_fallback_suggestions(meta)

        return jsonify({
            "status": "success",
            "source": "gemini_api",
            "model": GEMINI_MODEL,
            "ai_elapsed_seconds": ai_elapsed,
            "suggestions": validated_suggestions,
            "message": f"Gemini({GEMINI_MODEL})가 데이터셋을 진단하고 최적의 분석 도구를 추천했습니다."
        }), 200

    except Exception as e:
        logger.error(f"[AI] Gemini API 호출 중 오류 발생: {str(e)}", exc_info=True)
        suggestions = _get_fallback_suggestions(meta)
        return jsonify({
            "status": "success",
            "source": "error_fallback",
            "suggestions": suggestions,
            "message": f"Gemini API 호출 중 일시적 오류({str(e)})가 발생하여 기본 분석 도구를 제안합니다."
        }), 200

@app.route("/run", methods=["POST"])
def run_tool():
    """Step 18: 선택된 분석 도구를 Pandas로 실행하여 정밀 집계 결과 및 Chart.js 포맷 JSON 반환"""
    meta = CURRENT_DATASET.get("metadata")
    raw_df = CURRENT_DATASET.get("raw_df")

    if meta is None or raw_df is None:
        logger.error("[ERROR] 실행할 데이터셋이 메모리에 없습니다.")
        return jsonify({
            "status": "error",
            "message": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드해주세요."
        }), 400

    req_data = request.get_json(silent=True) or {}
    tool_name = req_data.get("tool", "channel_share_by_category")
    user_params = req_data.get("params", {})

    if not hasattr(tools, tool_name):
        logger.error(f"[ERROR] 요청된 도구가 tools.py에 존재하지 않음: {tool_name}")
        return jsonify({
            "status": "error",
            "message": f"요청하신 분석 도구('{tool_name}')는 지원되지 않는 도구입니다."
        }), 400

    tool_func = getattr(tools, tool_name)

    try:
        sig = inspect.signature(tool_func)
        call_args = {}

        if "df" in sig.parameters:
            call_args["df"] = raw_df
        if "meta" in sig.parameters:
            call_args["meta"] = meta

        for param_name, param_val in user_params.items():
            if param_name in sig.parameters and param_name not in ["df", "meta"]:
                call_args[param_name] = param_val

        result = tool_func(**call_args)
        CURRENT_DATASET["last_result"] = result

        return jsonify({
            "status": "success",
            "result": result,
            "message": f"도구 '{tool_name}' 분석 연산 및 차트 데이터 생성이 성공적으로 완료되었습니다."
        }), 200

    except Exception as e:
        logger.error(f"[ERROR] 도구 실행 실패 ({tool_name}): {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"분석 도구 '{tool_name}' 실행 중 오류가 발생했습니다: {str(e)}"
        }), 500

@app.route("/ask", methods=["POST"])
def ask_question():
    """
    신규 추가: 사용자의 자연어 데이터 질문 처리 (/ask)
    1. 사용자의 자연어 질문을 받아 Gemini 3.5 Flash Lite가 질문의 의도에 가장 적합한 도구(12개 중 1개)와 파라미터를 JSON으로 파싱.
    2. 파싱된 도구를 Pandas로 즉각 실행하여 확정 수치 테이블과 Chart.js 시각화 데이터를 생성.
    3. 계산된 팩트를 바탕으로 사용자 질문에 대한 명쾌한 자연어 답변 요약을 생성하여 반환.
    """
    meta = CURRENT_DATASET.get("metadata")
    raw_df = CURRENT_DATASET.get("raw_df")

    if not meta or raw_df is None:
        logger.error("[ERROR] 질문을 처리할 데이터셋이 없습니다.")
        return jsonify({"status": "error", "message": "먼저 CSV 파일을 업로드하여 진단을 완료해주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    user_query = str(req_data.get("query", "")).strip()
    if not user_query:
        return jsonify({"status": "error", "message": "질문 내용을 입력해주세요."}), 400

    cats = meta["categories"]["analyzable_list"]
    periods = meta["periods"]["all_list"]
    rec_period = meta["periods"]["recommended"]

    logger.info(f"[REQUEST] POST /ask - 자연어 질문 수신: '{user_query}'")

    # 1. Gemini를 통한 자연어 의도 -> 도구 및 파라미터 매핑 프롬프트
    mapping_prompt = f"""
당신은 사용자의 질문 의도를 분석하여 정확한 이커머스 채널 분석 도구와 파라미터로 연결하는 라우팅 엔진입니다.

[사용 가능한 14개 도구 목록]
- channel_share_by_category : 특정 시점의 전체 상품군별 온라인몰 vs 온·오프라인 병행몰 점유율 비교
- pure_online_dominance_top_n : 온라인몰 점유율이 가장 높은 상위 N개 상품군 발굴 (파라미터: top_n)
- omnichannel_dominance_top_n : 온·오프라인 병행몰 점유율이 가장 높은 상위 N개 상품군 발굴 (파라미터: top_n)
- macro_channel_ratio : 전체 거래액 중 온라인몰과 병행몰의 거시적 총 비중 (도넛 차트)
- category_channel_trend : 특정 상품군의 시계열(월별) 거래액 추이 (파라미터: category)
- channel_share_shift : 두 시점 간 병행몰 점유율 변화폭 (%p) (파라미터: base_period, target_period)
- total_volume_ranking : 전체 거래액 규모 상위 상품군 순위 (파라미터: top_n)
- growth_rate_by_channel : 채널별 전년비/기간별 거래액 성장률 비교 (파라미터: base_period, target_period)
- channel_dominance_matrix : 거래규모(X축) 대비 온라인몰 점유율(Y축) 4사분면 분류
- channel_basket_composition : 온라인몰 vs 병행몰 장바구니 매출 구성비 비교
- seasonal_channel_pattern : 특정 상품군의 월별 계절성 패턴 (파라미터: category)
- single_category_deep_dive : 선택한 1개 특정 상품군의 거래 규모, 채널 점유율, 시장 순위 종합 심층 요약 (파라미터: category)
- period_category_channel_trend : 특정 기간 범위(시작 시점~종료 시점) 동안 특정 상품군의 채널 거래액 추이 및 점유율 행태 변화 (파라미터: category, start_period, end_period)
- period_product_channel_behavior : 지정 기간 범위 동안 전 상품군별 온라인몰 점유율 변화폭 및 채널 선호 행태 비교 랭킹 (파라미터: start_period, end_period)

[데이터셋 정보]
- 상품군 목록: {', '.join(cats)}
- 시점 목록: {', '.join(periods)}
- 권장 시점: {rec_period}

[사용자 질문]
"{user_query}"

[출력 규칙]
반드시 아래 JSON 형식으로만 응답하십시오.
{{
  "tool": "선택한 도구 영문명 (14개 중 1개)",
  "params": {{
    "reference_period": "{rec_period}",
    "category": "질문에 특정 품목이 언급되었다면 위 상품군 목록 중 가장 일치하는 것",
    "start_period": "{periods[0]}",
    "end_period": "{rec_period}",
    "top_n": 5
  }},
  "thought": "이 도구를 선택한 이유 요약 (1문장)"
}}
"""

    selected_tool = "channel_share_by_category"
    parsed_params = {"reference_period": rec_period, "exclude_aggregates": True}
    thought = "기본 채널 점유율 비교 분석"

    # API Key 확인 및 의도 파악
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=mapping_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            raw_text = resp.text.strip()
            parsed_json = json.loads(raw_text)
            if parsed_json.get("tool") in [
                "channel_share_by_category", "pure_online_dominance_top_n", "omnichannel_dominance_top_n",
                "macro_channel_ratio", "category_channel_trend", "channel_share_shift",
                "total_volume_ranking", "growth_rate_by_channel", "channel_dominance_matrix",
                "channel_basket_composition", "seasonal_channel_pattern", "single_category_deep_dive",
                "period_category_channel_trend", "period_product_channel_behavior"
            ]:
                selected_tool = parsed_json["tool"]
                parsed_params = parsed_json.get("params", {})
                parsed_params["exclude_aggregates"] = True
                thought = parsed_json.get("thought", "")
                logger.info(f"[AI] 자연어 질문 의도 매핑 완료: 도구={selected_tool}, 파라미터={parsed_params}")
        except Exception as e:
            logger.warning(f"[AI] 자연어 의도 파악 중 오류({str(e)}), 기본 키워드 룰 매핑 적용")
            # 룰 기반 키워드 매칭
            for c in cats:
                if c in user_query:
                    selected_tool = "single_category_deep_dive"
                    parsed_params["category"] = c
                    thought = f"'{c}' 상품군에 대한 질문으로 파악하여 종합 진단을 수행합니다."
                    break
    else:
        # 키 미설정 시 기본 키워드 매칭
        for c in cats:
            if c in user_query:
                selected_tool = "single_category_deep_dive"
                parsed_params["category"] = c
                thought = f"'{c}' 상품군 질문으로 매핑"
                break
        if "비중" in user_query or "전체" in user_query or "총" in user_query:
            selected_tool = "macro_channel_ratio"

    # 2. 파싱된 도구를 Pandas로 즉시 정밀 계산
    tool_func = getattr(tools, selected_tool, tools.channel_share_by_category)
    sig = inspect.signature(tool_func)
    call_args = {}
    if "df" in sig.parameters:
        call_args["df"] = raw_df
    if "meta" in sig.parameters:
        call_args["meta"] = meta
    for k, v in parsed_params.items():
        if k in sig.parameters and k not in ["df", "meta"]:
            call_args[k] = v

    calc_result = tool_func(**call_args)
    CURRENT_DATASET["last_result"] = calc_result

    # 3. 계산 결과를 바탕으로 사용자 질문에 대한 직접적 답변 문장 생성
    answer_text = f"**질문 답변:** {calc_result['summary']}"
    if selected_tool == "macro_channel_ratio":
        t0 = calc_result["table_data"][0]
        t1 = calc_result["table_data"][1]
        answer_text = f"**질문 답변:** {calc_result['reference_period']} 기준 전체 거래액 중 **온라인몰이 {t0['share_pct']}%**, **온·오프라인 병행몰이 {t1['share_pct']}%**를 차지하고 있습니다."
    elif selected_tool in ["pure_online_dominance_top_n", "omnichannel_dominance_top_n"]:
        top1 = calc_result["table_data"][0]
        share_key = "pure_online_share_pct" if "pure_online" in selected_tool else "omnichannel_share_pct"
        ch_name = "온라인몰" if "pure_online" in selected_tool else "온·오프라인 병행몰"
        answer_text = f"**질문 답변:** {calc_result['reference_period']} 기준 {ch_name} 점유율 1위 품목은 **'{top1['category']}'**이며, 점유율은 **{top1[share_key]}%**입니다."
    elif selected_tool == "single_category_deep_dive":
        cat_name = parsed_params.get("category", "")
        answer_text = f"**질문 답변:** {calc_result['summary']}"
    elif selected_tool == "period_category_channel_trend":
        m = calc_result.get("meta", {})
        cat = m.get("category", "")
        on_g = m.get("online_growth_pct", 0)
        om_g = m.get("omni_growth_pct", 0)
        shift = m.get("share_shift_pctp", 0)
        answer_text = f"**질문 답변:** {calc_result['reference_period']} 동안 **'{cat}'** 상품군은 온라인몰 거래액 {on_g:+}%, 온·오프라인 병행몰 {om_g:+}% 성장률을 기록했으며, 온라인몰 점유율은 **{shift:+} %p** 변화했습니다. {calc_result['summary']}"
    elif selected_tool == "period_product_channel_behavior":
        m = calc_result.get("meta", {})
        top_on = m.get("top_online_category", "")
        top_on_s = m.get("top_online_shift", 0)
        top_om = m.get("top_omni_category", "")
        top_om_s = m.get("top_omni_shift", 0)
        answer_text = f"**질문 답변:** {calc_result['reference_period']} 동안 온라인몰 점유율이 가장 크게 증가한 품목은 **'{top_on}'(+{top_on_s}%p)**이며, 병행몰 선호가 가장 크게 확대된 품목은 **'{top_om}'({top_om_s}%p)**입니다."

    logger.info(f"[CALCULATE] /ask 실행 완료: {selected_tool} 결과 도출")

    return jsonify({
        "status": "success",
        "query": user_query,
        "mapped_tool": selected_tool,
        "tool_title": calc_result["tool_title"],
        "thought": thought,
        "answer": answer_text,
        "result": calc_result
    }), 200

@app.route("/explain", methods=["POST"])
def explain_insight():
    """Step 19: Gemini 인사이트 리포트 생성 (모드 A / 모드 B)"""
    meta = CURRENT_DATASET.get("metadata")
    last_res = CURRENT_DATASET.get("last_result")

    if not last_res and CURRENT_DATASET.get("raw_df") is not None:
        last_res = tools.channel_share_by_category(CURRENT_DATASET["raw_df"], meta)
        CURRENT_DATASET["last_result"] = last_res

    if not meta or not last_res:
        logger.error("[ERROR] 설명할 분석 결과가 없습니다.")
        return jsonify({
            "status": "error",
            "message": "먼저 분석 도구를 실행(/run)하여 계산 결과를 생성해주세요."
        }), 400

    req_data = request.get_json(silent=True) or {}
    mode = str(req_data.get("mode", "B")).strip().upper()
    if mode not in ["A", "B"]:
        mode = "B"

    ref_period = last_res.get("reference_period", "")
    unit = last_res.get("unit", "백만원")
    tool_title = last_res.get("tool_title", "")
    table_data = last_res.get("table_data", [])

    if mode == "A":
        cats_str = ", ".join(meta["categories"]["analyzable_list"][:6])
        prompt = f"""
당신은 일반 AI입니다.
현재 업로드된 통계 데이터의 메타정보는 다음과 같습니다:
- 대상 상품군: {cats_str} 등
- 운영 형태: 온라인몰(순수 온라인몰), 온·오프라인 병행몰
- 기준 시점: {ref_period}

질문: 소비자들이 위 상품군들을 구매할 때 온라인몰과 병행몰 중 어디를 더 많이 이용하는지 대략적으로 분석해줘.
(주의: 별도의 집계 수치 표는 제공되지 않았으므로 당신의 일반 지식으로 추정하여 서술하십시오.)
"""
    else:
        table_json_str = json.dumps(table_data, ensure_ascii=False, indent=2)
        prompt = f"""
당신은 대한민국 이커머스 유통 채널(온라인몰 vs 온·오프라인 병행몰) 전문 수석 분석가입니다.
아래에 제공된 [Pandas 확정 계산 결과 테이블]만을 철저히 근거로 삼아 경영진을 위한 객관적 채널 분석 리포트를 작성하십시오.

[분석 도구 정보]
- 도구명: {tool_title}
- 기준 시점: {ref_period}
- 거래액 단위: {unit}
- 분석 품목 수: {len(table_data)}개 상품군 (합계/총계 행은 이중 계산 방지를 위해 사전 제외됨)

[Pandas 확정 계산 결과 테이블 (임의 재계산 절대 금지, 본 수치만 인용할 것)]
{table_json_str}

[작성 절대 준수 규칙]
1. 반드시 위 테이블에 기재된 점유율(%), 거래액 수치만을 사실로 인용하십시오. 직접 수치를 재계산하거나 임의로 숫자를 조작/추정하지 마십시오.
2. 본문 서두에 기준 시점({ref_period})과 금액 단위({unit}), 점유율(%)을 명확히 명시하십시오.
3. 온라인몰 우세 상품군(점유율 50% 이상)과 병행몰 우세 상품군을 명확히 구분하고, 유통 특성(예: 규격화/가격비교 용이성 vs 신선도/체험/브랜드 신뢰도)에 따른 원인을 해석하십시오.
4. 데이터에 명시되지 않은 외부 요인은 단정하지 말고 "가설" 또는 "이 데이터로는 확인할 수 없음"으로 엄격히 선을 그으십시오.
5. 이커머스 실무 초년생도 직관적으로 이해할 수 있는 평이하고 단정한 비즈니스 리포트 문체로 작성하십시오.

[반드시 준수할 출력 마크다운 서식]
## 분석 개요 및 기준 시점
## 핵심 수치 요약 (Key Numbers)
## 상품군별 채널 지배력 분석 (온라인몰 강세 vs 병행몰 강세)
## 채널 선호도 차이의 주요 원인 및 소비자 행동 해석
## 데이터의 한계 및 추가 확인이 필요한 사항
"""

    start_ai_time = time.time()

    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        logger.info(f"[AI] Gemini API Key 미설정: 규칙 기반 Fallback 리포트 반환 (모드 {mode})")
        report_md = _generate_fallback_explain_report(mode, last_res, meta)
        return jsonify({
            "status": "success",
            "source": "rule_based_fallback",
            "mode": mode,
            "report_markdown": report_md,
            "message": f"Gemini API 키가 아직 설정되지 않아 모드 {mode} 표준 리포트를 반환합니다."
        }), 200

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3 if mode == "B" else 0.7
            )
        )

        ai_elapsed = round(time.time() - start_ai_time, 3)
        report_text = response.text.strip()
        logger.info(f"[AI] Gemini 인사이트 리포트 생성 완료 (모드: {mode}, 소요시간: {ai_elapsed}s, 모델: {GEMINI_MODEL})")

        return jsonify({
            "status": "success",
            "source": "gemini_api",
            "model": GEMINI_MODEL,
            "mode": mode,
            "ai_elapsed_seconds": ai_elapsed,
            "report_markdown": report_text,
            "message": f"Gemini({GEMINI_MODEL})가 모드 {mode} 리포트를 성공적으로 생성했습니다."
        }), 200

    except Exception as e:
        logger.error(f"[AI] Gemini 리포트 생성 실패: {str(e)}", exc_info=True)
        report_md = _generate_fallback_explain_report(mode, last_res, meta)
        return jsonify({
            "status": "success",
            "source": "error_fallback",
            "mode": mode,
            "report_markdown": report_md,
            "message": f"Gemini API 호출 일시적 오류({str(e)})로 기본 분석 리포트를 제공합니다."
        }), 200

@app.errorhandler(413)
def request_entity_too_large(error):
    logger.error(f"[ERROR] 파일 크기 초과: 최대 {max_upload_mb}MB까지 업로드 가능합니다.")
    return jsonify({
        "status": "error",
        "message": f"파일 크기가 너무 큽니다. 최대 {max_upload_mb}MB까지 지원합니다."
    }), 413

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"[ERROR] 예외 발생: {str(e)}", exc_info=True)
    return jsonify({
        "status": "error",
        "message": f"서버 내부 오류: {str(e)}"
    }), 500

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "true").lower() in ("true", "1", "t")
    logger.info(f"[SERVER] Starting Flask on http://127.0.0.1:5000 (Model: {GEMINI_MODEL}, Debug: {debug_mode})")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
