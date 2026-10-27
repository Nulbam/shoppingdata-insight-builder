"""
tools.py - E-Commerce Channel Insight Analyzer 도구 카탈로그
온라인몰 vs 온·오프라인 병행몰 비교 분석 엔진 (총 12개 도구 완성본)
"""

import time
import logging
import re
import pandas as pd
import numpy as np

logger = logging.getLogger("ChannelAnalyzer")

def _normalize_channel_name(val):
    """운영형태 명칭을 표준 명칭(온라인몰 / 온·오프라인 병행몰)으로 정규화"""
    s = str(val).strip()
    if any(k in s for k in ["온·오프", "온/오프", "온오프", "병행"]):
        return "온·오프라인 병행몰"
    elif "온라인" in s:
        return "온라인몰"
    return s

def _prepare_filtered_df(df, meta, reference_period=None, exclude_aggregates=True):
    """
    분석 기준 시점 및 집계(합계) 행 필터링 헬퍼
    """
    det = meta.get("detected_columns", {})
    cat_col = det.get("category_col")
    op_col = det.get("operation_col")
    time_col = det.get("period_col")
    val_col = det.get("volume_col")
    unit = det.get("unit", "백만원")

    working_df = df.copy()

    # 집계(합계/계) 행 필터링
    initial_rows = len(working_df)
    if exclude_aggregates:
        agg_keywords = ["합계", "총계", "소계", "계", "전체"]
        cat_mask = (
            working_df[cat_col].astype(str).str.strip().isin(agg_keywords) |
            working_df[cat_col].astype(str).str.contains(r"^합계|^총계|\(계\)", regex=True)
        )
        op_mask = working_df[op_col].astype(str).str.strip().isin(agg_keywords)
        working_df = working_df[~(cat_mask | op_mask)]

    excluded_rows = initial_rows - len(working_df)

    # 기준 시점 결정 (지정 없으면 가장 최근 시점)
    if not reference_period:
        periods = sorted([str(p).strip() for p in working_df[time_col].dropna().unique()])
        reference_period = periods[-1] if periods else ""

    period_df = working_df[working_df[time_col].astype(str).str.strip() == str(reference_period).strip()].copy()
    period_df["_std_channel"] = period_df[op_col].apply(_normalize_channel_name)

    return period_df, reference_period, cat_col, op_col, time_col, val_col, unit, excluded_rows

# ==============================================================================
# 도구 1: channel_share_by_category (상품군별 온라인몰 vs 병행몰 점유율 100% 누적 막대)
# ==============================================================================
def channel_share_by_category(df, meta, reference_period=None, exclude_aggregates=True):
    start_time = time.time()
    p_df, ref_period, cat_col, op_col, time_col, val_col, unit, excluded_rows = _prepare_filtered_df(
        df, meta, reference_period, exclude_aggregates
    )

    pivot = p_df.pivot_table(
        index=cat_col,
        columns="_std_channel",
        values=val_col,
        aggfunc="sum",
        fill_value=0.0
    ).reset_index()

    if "온라인몰" not in pivot.columns:
        pivot["온라인몰"] = 0.0
    if "온·오프라인 병행몰" not in pivot.columns:
        pivot["온·오프라인 병행몰"] = 0.0

    pivot["총거래액"] = pivot["온라인몰"] + pivot["온·오프라인 병행몰"]
    
    pivot["온라인몰점유율"] = np.where(
        pivot["총거래액"] > 0,
        np.round((pivot["온라인몰"] / pivot["총거래액"]) * 100, 2),
        0.0
    )
    pivot["병행몰점유율"] = np.where(
        pivot["총거래액"] > 0,
        np.round((pivot["온·오프라인 병행몰"] / pivot["총거래액"]) * 100, 2),
        0.0
    )

    pivot = pivot.sort_values(by="온라인몰점유율", ascending=False)

    table_data = []
    for _, row in pivot.iterrows():
        table_data.append({
            "category": str(row[cat_col]),
            "pure_online_volume": float(row["온라인몰"]),
            "omnichannel_volume": float(row["온·오프라인 병행몰"]),
            "total_volume": float(row["총거래액"]),
            "pure_online_share_pct": float(row["온라인몰점유율"]),
            "omnichannel_share_pct": float(row["병행몰점유율"]),
            "dominant_channel": "온라인몰" if row["온라인몰점유율"] >= 50.0 else "온·오프라인 병행몰"
        })

    labels = [r["category"] for r in table_data]
    online_shares = [r["pure_online_share_pct"] for r in table_data]
    omni_shares = [r["omnichannel_share_pct"] for r in table_data]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "온라인몰 (%)",
                    "data": online_shares,
                    "backgroundColor": "rgba(54, 162, 235, 0.8)",
                    "borderColor": "rgba(54, 162, 235, 1)",
                    "borderWidth": 1
                },
                {
                    "label": "온·오프라인 병행몰 (%)",
                    "data": omni_shares,
                    "backgroundColor": "rgba(255, 99, 132, 0.8)",
                    "borderColor": "rgba(255, 99, 132, 1)",
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "indexAxis": "x",
            "scales": {
                "x": {"stacked": True},
                "y": {"stacked": True, "max": 100, "title": {"display": True, "text": "점유율 (%)"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] channel_share_by_category 완료 (소요시간: {elapsed}s, 결과 행 수: {len(table_data)})")

    return {
        "tool_name": "channel_share_by_category",
        "tool_title": "상품군별 채널 점유율 비교 (100% 누적 막대)",
        "reference_period": ref_period,
        "unit": unit,
        "meta": {
            "used_rows": len(p_df),
            "excluded_rows": excluded_rows,
            "category_count": len(table_data)
        },
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"{ref_period} 기준 총 {len(table_data)}개 상품군의 온라인몰 vs 온·오프라인 병행몰 점유율 분석 결과입니다."
    }

# ==============================================================================
# 도구 2: pure_online_dominance_top_n (온라인몰 점유율 상위 N개 상품군 수평 막대)
# ==============================================================================
def pure_online_dominance_top_n(df, meta, reference_period=None, top_n=5, exclude_aggregates=True):
    start_time = time.time()
    res = channel_share_by_category(df, meta, reference_period, exclude_aggregates)
    sorted_data = sorted(res["table_data"], key=lambda x: x["pure_online_share_pct"], reverse=True)
    top_data = sorted_data[:int(top_n)]

    labels = [r["category"] for r in top_data]
    shares = [r["pure_online_share_pct"] for r in top_data]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "온라인몰 점유율 (%)",
                    "data": shares,
                    "backgroundColor": "rgba(54, 162, 235, 0.85)",
                    "borderColor": "rgba(54, 162, 235, 1)",
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "indexAxis": "y",
            "scales": {
                "x": {"max": 100, "title": {"display": True, "text": "점유율 (%)"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] pure_online_dominance_top_n 완료 (소요시간: {elapsed}s, 상위 {len(top_data)}개)")

    return {
        "tool_name": "pure_online_dominance_top_n",
        "tool_title": f"온라인몰 우세 상위 {len(top_data)}대 상품군 (수평 막대)",
        "reference_period": res["reference_period"],
        "unit": res["unit"],
        "meta": res["meta"],
        "table_data": top_data,
        "chart_data": chart_data,
        "summary": f"{res['reference_period']} 기준 순수 온라인몰 점유율이 가장 높은 상위 {len(top_data)}개 상품군입니다."
    }

# ==============================================================================
# 도구 3: omnichannel_dominance_top_n (온·오프라인 병행몰 점유율 상위 N개 상품군 수평 막대)
# ==============================================================================
def omnichannel_dominance_top_n(df, meta, reference_period=None, top_n=5, exclude_aggregates=True):
    start_time = time.time()
    res = channel_share_by_category(df, meta, reference_period, exclude_aggregates)
    sorted_data = sorted(res["table_data"], key=lambda x: x["omnichannel_share_pct"], reverse=True)
    top_data = sorted_data[:int(top_n)]

    labels = [r["category"] for r in top_data]
    shares = [r["omnichannel_share_pct"] for r in top_data]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "온·오프라인 병행몰 점유율 (%)",
                    "data": shares,
                    "backgroundColor": "rgba(255, 99, 132, 0.85)",
                    "borderColor": "rgba(255, 99, 132, 1)",
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "indexAxis": "y",
            "scales": {
                "x": {"max": 100, "title": {"display": True, "text": "점유율 (%)"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] omnichannel_dominance_top_n 완료 (소요시간: {elapsed}s, 상위 {len(top_data)}개)")

    return {
        "tool_name": "omnichannel_dominance_top_n",
        "tool_title": f"온·오프라인 병행몰 우세 상위 {len(top_data)}대 상품군 (수평 막대)",
        "reference_period": res["reference_period"],
        "unit": res["unit"],
        "meta": res["meta"],
        "table_data": top_data,
        "chart_data": chart_data,
        "summary": f"{res['reference_period']} 기준 온·오프라인 병행몰 점유율이 가장 높은 상위 {len(top_data)}개 상품군입니다."
    }

# ==============================================================================
# 도구 4: macro_channel_ratio (전체 거래액 중 온라인몰 vs 병행몰 거시적 총 비중 도넛 차트)
# ==============================================================================
def macro_channel_ratio(df, meta, reference_period=None, exclude_aggregates=True):
    start_time = time.time()
    p_df, ref_period, cat_col, op_col, time_col, val_col, unit, excluded_rows = _prepare_filtered_df(
        df, meta, reference_period, exclude_aggregates
    )

    channel_sums = p_df.groupby("_std_channel")[val_col].sum()
    online_total = float(channel_sums.get("온라인몰", 0.0))
    omni_total = float(channel_sums.get("온·오프라인 병행몰", 0.0))
    grand_total = online_total + omni_total

    online_pct = round((online_total / grand_total) * 100, 2) if grand_total > 0 else 0.0
    omni_pct = round((omni_total / grand_total) * 100, 2) if grand_total > 0 else 0.0

    table_data = [
        {"channel": "온라인몰", "volume": online_total, "share_pct": online_pct},
        {"channel": "온·오프라인 병행몰", "volume": omni_total, "share_pct": omni_pct},
        {"channel": "총합계", "volume": grand_total, "share_pct": 100.0}
    ]

    chart_data = {
        "type": "doughnut",
        "data": {
            "labels": ["온라인몰", "온·오프라인 병행몰"],
            "datasets": [
                {
                    "data": [online_total, omni_total],
                    "backgroundColor": [
                        "rgba(54, 162, 235, 0.85)",
                        "rgba(255, 99, 132, 0.85)"
                    ],
                    "borderColor": ["#ffffff", "#ffffff"],
                    "borderWidth": 2
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "legend": {"position": "bottom"}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] macro_channel_ratio 완료 (소요시간: {elapsed}s, 총거래액: {grand_total:,.0f} {unit})")

    return {
        "tool_name": "macro_channel_ratio",
        "tool_title": "전체 거래액 채널 총 비중 (도넛 차트)",
        "reference_period": ref_period,
        "unit": unit,
        "meta": {
            "used_rows": len(p_df),
            "excluded_rows": excluded_rows,
            "grand_total_volume": grand_total
        },
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"{ref_period} 기준 전체 거래액({grand_total:,.0f} {unit}) 중 온라인몰 {online_pct}%, 온·오프라인 병행몰 {omni_pct}% 비중입니다."
    }

# ==============================================================================
# 도구 5: category_channel_trend (특정 상품군의 시계열 운영형태별 거래액 추이 선 차트)
# ==============================================================================
def category_channel_trend(df, meta, category=None, exclude_aggregates=True):
    start_time = time.time()
    det = meta.get("detected_columns", {})
    cat_col = det.get("category_col")
    op_col = det.get("operation_col")
    time_col = det.get("period_col")
    val_col = det.get("volume_col")
    unit = det.get("unit", "백만원")

    working_df = df.copy()
    initial_rows = len(working_df)

    if exclude_aggregates:
        agg_keywords = ["합계", "총계", "소계", "계", "전체"]
        cat_mask = (
            working_df[cat_col].astype(str).str.strip().isin(agg_keywords) |
            working_df[cat_col].astype(str).str.contains(r"^합계|^총계|\(계\)", regex=True)
        )
        op_mask = working_df[op_col].astype(str).str.strip().isin(agg_keywords)
        working_df = working_df[~(cat_mask | op_mask)]

    excluded_rows = initial_rows - len(working_df)
    working_df["_std_channel"] = working_df[op_col].apply(_normalize_channel_name)

    available_cats = working_df[cat_col].dropna().unique().tolist()
    if not category or category not in available_cats:
        top_cat = working_df.groupby(cat_col)[val_col].sum().idxmax()
        category = str(top_cat)

    cat_df = working_df[working_df[cat_col].astype(str).str.strip() == str(category).strip()].copy()
    
    pivot = cat_df.pivot_table(
        index=time_col,
        columns="_std_channel",
        values=val_col,
        aggfunc="sum",
        fill_value=0.0
    ).reset_index()

    pivot = pivot.sort_values(by=time_col, ascending=True)

    if "온라인몰" not in pivot.columns:
        pivot["온라인몰"] = 0.0
    if "온·오프라인 병행몰" not in pivot.columns:
        pivot["온·오프라인 병행몰"] = 0.0

    pivot["총거래액"] = pivot["온라인몰"] + pivot["온·오프라인 병행몰"]
    pivot["온라인몰점유율"] = np.where(
        pivot["총거래액"] > 0,
        np.round((pivot["온라인몰"] / pivot["총거래액"]) * 100, 2),
        0.0
    )

    table_data = []
    for _, row in pivot.iterrows():
        table_data.append({
            "period": str(row[time_col]),
            "category": category,
            "pure_online_volume": float(row["온라인몰"]),
            "omnichannel_volume": float(row["온·오프라인 병행몰"]),
            "total_volume": float(row["총거래액"]),
            "pure_online_share_pct": float(row["온라인몰점유율"])
        })

    periods = [r["period"] for r in table_data]
    online_vols = [r["pure_online_volume"] for r in table_data]
    omni_vols = [r["omnichannel_volume"] for r in table_data]

    chart_data = {
        "type": "line",
        "data": {
            "labels": periods,
            "datasets": [
                {
                    "label": f"온라인몰 ({unit})",
                    "data": online_vols,
                    "borderColor": "rgba(54, 162, 235, 1)",
                    "backgroundColor": "rgba(54, 162, 235, 0.15)",
                    "fill": True,
                    "tension": 0.2
                },
                {
                    "label": f"온·오프라인 병행몰 ({unit})",
                    "data": omni_vols,
                    "borderColor": "rgba(255, 99, 132, 1)",
                    "backgroundColor": "rgba(255, 99, 132, 0.15)",
                    "fill": True,
                    "tension": 0.2
                }
            ]
        },
        "options": {
            "responsive": True,
            "scales": {
                "y": {"title": {"display": True, "text": f"거래액 ({unit})"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] category_channel_trend 완료 ({category}, 시점 수: {len(periods)}, 소요: {elapsed}s)")

    return {
        "tool_name": "category_channel_trend",
        "tool_title": f"'{category}' 채널별 시계열 거래액 추이 (다중 선 차트)",
        "reference_period": f"{periods[0]} ~ {periods[-1]}" if periods else "",
        "unit": unit,
        "meta": {
            "category": category,
            "used_rows": len(cat_df),
            "excluded_rows": excluded_rows,
            "periods_count": len(periods)
        },
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"'{category}' 상품군의 {periods[0] if periods else ''}부터 {periods[-1] if periods else ''}까지 온라인몰과 병행몰 시계열 거래액 변화 추이입니다."
    }

# ==============================================================================
# 도구 6: channel_share_shift (두 시점 간 상품군별 온·오프라인 병행몰 점유율 변화폭 %p)
# ==============================================================================
def channel_share_shift(df, meta, base_period=None, target_period=None, exclude_aggregates=True):
    start_time = time.time()
    periods = meta.get("periods", {}).get("all_list", [])

    if len(periods) < 2:
        logger.info("[CALCULATE] channel_share_shift: 시점이 1개뿐이므로 단일 시점 점유율로 자동 대체")
        res = channel_share_by_category(df, meta, reference_period=periods[0] if periods else None)
        res["tool_title"] = "시계열 비교 불가 (단일 시점 점유율 표시)"
        res["summary"] = "업로드된 데이터셋에 시점이 1개만 존재하여 점유율 전이 대신 기준 시점 점유율을 표시합니다."
        return res

    if not base_period:
        base_period = periods[0]
    if not target_period:
        target_period = periods[-1]

    res_base = channel_share_by_category(df, meta, reference_period=base_period, exclude_aggregates=exclude_aggregates)
    res_target = channel_share_by_category(df, meta, reference_period=target_period, exclude_aggregates=exclude_aggregates)

    base_map = {r["category"]: r["omnichannel_share_pct"] for r in res_base["table_data"]}
    target_map = {r["category"]: r["omnichannel_share_pct"] for r in res_target["table_data"]}
    target_vol_map = {r["category"]: r["total_volume"] for r in res_target["table_data"]}

    all_cats = sorted(list(set(base_map.keys()) & set(target_map.keys())))

    table_data = []
    for c in all_cats:
        b_pct = base_map[c]
        t_pct = target_map[c]
        shift = round(t_pct - b_pct, 2)
        table_data.append({
            "category": c,
            "base_period": base_period,
            "target_period": target_period,
            "base_omnichannel_pct": b_pct,
            "target_omnichannel_pct": t_pct,
            "shift_pp": shift,
            "target_total_volume": target_vol_map.get(c, 0.0),
            "trend": "병행몰 비중 확대" if shift > 0 else ("온라인몰 비중 확대" if shift < 0 else "변화 없음")
        })

    table_data = sorted(table_data, key=lambda x: x["shift_pp"], reverse=True)

    labels = [r["category"] for r in table_data]
    shifts = [r["shift_pp"] for r in table_data]
    bg_colors = ["rgba(255, 99, 132, 0.8)" if s >= 0 else "rgba(54, 162, 235, 0.8)" for s in shifts]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": f"병행몰 점유율 변화폭 (%p: {base_period} -> {target_period})",
                    "data": shifts,
                    "backgroundColor": bg_colors,
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "indexAxis": "x",
            "scales": {
                "y": {"title": {"display": True, "text": "점유율 변화폭 (%p)"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] channel_share_shift 완료 ({base_period}->{target_period}, 소요: {elapsed}s)")

    return {
        "tool_name": "channel_share_shift",
        "tool_title": f"시점 간 병행몰 점유율 전이/변화폭 ({base_period} vs {target_period})",
        "reference_period": f"{base_period} vs {target_period}",
        "unit": "%p",
        "meta": {
            "base_period": base_period,
            "target_period": target_period,
            "compared_categories": len(table_data)
        },
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"{base_period} 대비 {target_period} 시점 간 상품군별 온·오프라인 병행몰 점유율 변화폭(%p) 분석 결과입니다."
    }

# ==============================================================================
# 도구 7: total_volume_ranking (전체 거래액 상위 상품군 순위 및 채널 누적 구성)
# ==============================================================================
def total_volume_ranking(df, meta, reference_period=None, top_n=10, exclude_aggregates=True):
    start_time = time.time()
    res = channel_share_by_category(df, meta, reference_period, exclude_aggregates)
    sorted_by_vol = sorted(res["table_data"], key=lambda x: x["total_volume"], reverse=True)
    top_data = sorted_by_vol[:int(top_n)]

    for idx, r in enumerate(top_data, start=1):
        r["rank"] = idx

    labels = [f"{r['rank']}위. {r['category']}" for r in top_data]
    online_vols = [r["pure_online_volume"] for r in top_data]
    omni_vols = [r["omnichannel_volume"] for r in top_data]

    unit = res["unit"]
    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": f"온라인몰 거래액 ({unit})",
                    "data": online_vols,
                    "backgroundColor": "rgba(54, 162, 235, 0.85)",
                    "borderWidth": 1
                },
                {
                    "label": f"온·오프라인 병행몰 거래액 ({unit})",
                    "data": omni_vols,
                    "backgroundColor": "rgba(255, 99, 132, 0.85)",
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "indexAxis": "x",
            "scales": {
                "x": {"stacked": True},
                "y": {"stacked": True, "title": {"display": True, "text": f"거래액 ({unit})"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] total_volume_ranking 완료 (상위 {len(top_data)}개, 소요: {elapsed}s)")

    return {
        "tool_name": "total_volume_ranking",
        "tool_title": f"전체 거래액 상위 {len(top_data)}대 상품군 및 채널 구성 (누적 막대)",
        "reference_period": res["reference_period"],
        "unit": unit,
        "meta": {
            "top_n": len(top_data),
            "reference_period": res["reference_period"]
        },
        "table_data": top_data,
        "chart_data": chart_data,
        "summary": f"{res['reference_period']} 기준 전체 거래 규모 상위 {len(top_data)}대 품목과 채널 구성입니다."
    }

# ==============================================================================
# 도구 8: growth_rate_by_channel (채널별 전년비/기간별 거래액 성장률 비교)
# ==============================================================================
def growth_rate_by_channel(df, meta, base_period=None, target_period=None, exclude_aggregates=True):
    start_time = time.time()
    periods = meta.get("periods", {}).get("all_list", [])

    if len(periods) < 2:
        logger.info("[CALCULATE] growth_rate_by_channel: 시점이 1개뿐이므로 거래액 순위로 자동 대체")
        res = total_volume_ranking(df, meta, reference_period=periods[0] if periods else None)
        res["tool_title"] = "시계열 성장률 비교 불가 (단일 시점 거래 규모 표시)"
        res["summary"] = "업로드된 데이터셋에 시점이 1개만 존재하여 기간 성장률 대신 기준 시점 거래액 규모를 표시합니다."
        return res

    if not base_period:
        base_period = periods[0]
    if not target_period:
        target_period = periods[-1]

    res_base = channel_share_by_category(df, meta, reference_period=base_period, exclude_aggregates=exclude_aggregates)
    res_target = channel_share_by_category(df, meta, reference_period=target_period, exclude_aggregates=exclude_aggregates)

    base_dict = {r["category"]: r for r in res_base["table_data"]}
    target_dict = {r["category"]: r for r in res_target["table_data"]}

    all_cats = sorted(list(set(base_dict.keys()) & set(target_dict.keys())))

    table_data = []
    for c in all_cats:
        b_r = base_dict[c]
        t_r = target_dict[c]

        b_on = b_r["pure_online_volume"]
        t_on = t_r["pure_online_volume"]
        on_growth = round(((t_on - b_on) / b_on) * 100, 2) if b_on > 0 else 0.0

        b_om = b_r["omnichannel_volume"]
        t_om = t_r["omnichannel_volume"]
        om_growth = round(((t_om - b_om) / b_om) * 100, 2) if b_om > 0 else 0.0

        table_data.append({
            "category": c,
            "base_period": base_period,
            "target_period": target_period,
            "pure_online_growth_pct": on_growth,
            "omnichannel_growth_pct": om_growth,
            "growth_gap_pp": round(on_growth - om_growth, 2),
            "faster_growing_channel": "온라인몰" if on_growth > om_growth else ("온·오프라인 병행몰" if om_growth > on_growth else "동일")
        })

    table_data = sorted(table_data, key=lambda x: max(x["pure_online_growth_pct"], x["omnichannel_growth_pct"]), reverse=True)

    labels = [r["category"] for r in table_data]
    on_growths = [r["pure_online_growth_pct"] for r in table_data]
    om_growths = [r["omnichannel_growth_pct"] for r in table_data]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": f"온라인몰 성장률 (%)",
                    "data": on_growths,
                    "backgroundColor": "rgba(54, 162, 235, 0.8)",
                    "borderColor": "rgba(54, 162, 235, 1)",
                    "borderWidth": 1
                },
                {
                    "label": f"온·오프라인 병행몰 성장률 (%)",
                    "data": om_growths,
                    "backgroundColor": "rgba(255, 99, 132, 0.8)",
                    "borderColor": "rgba(255, 99, 132, 1)",
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "indexAxis": "x",
            "scales": {
                "y": {"title": {"display": True, "text": "성장률 (%)"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] growth_rate_by_channel 완료 ({base_period}->{target_period}, 소요: {elapsed}s)")

    return {
        "tool_name": "growth_rate_by_channel",
        "tool_title": f"채널별 거래액 성장률 비교 ({base_period} 대비 {target_period})",
        "reference_period": f"{base_period} vs {target_period}",
        "unit": "%",
        "meta": {
            "base_period": base_period,
            "target_period": target_period,
            "compared_categories": len(table_data)
        },
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"{base_period} 대비 {target_period} 상품군별 온라인몰 및 병행몰 거래액 성장률(%) 비교 분석 결과입니다."
    }

# ==============================================================================
# 도구 9: channel_dominance_matrix (거래규모 대비 온라인몰 점유율 사분면 산점도)
# ==============================================================================
def channel_dominance_matrix(df, meta, reference_period=None, exclude_aggregates=True):
    """
    X축(전체 거래규모) vs Y축(온라인몰 점유율)을 기준으로 4사분면으로 분류하는 전략적 포트폴리오 산점도
    """
    start_time = time.time()
    res = channel_share_by_category(df, meta, reference_period, exclude_aggregates)
    t_data = res["table_data"]

    if not t_data:
        return res

    vols = [r["total_volume"] for r in t_data]
    median_vol = float(np.median(vols)) if vols else 0.0

    table_data = []
    scatter_points = []

    for r in t_data:
        vol = r["total_volume"]
        share = r["pure_online_share_pct"]
        is_high_vol = vol >= median_vol
        is_high_share = share >= 50.0

        if is_high_vol and is_high_share:
            quadrant = "Q1: 대형 핵심 온라인 지배"
        elif not is_high_vol and is_high_share:
            quadrant = "Q2: 니치/틈새 온라인 특화"
        elif not is_high_vol and not is_high_share:
            quadrant = "Q3: 니치/소형 병행몰 우세"
        else:
            quadrant = "Q4: 대형 주력 병행몰 수성"

        row_item = {
            "category": r["category"],
            "total_volume": vol,
            "pure_online_share_pct": share,
            "omnichannel_share_pct": r["omnichannel_share_pct"],
            "quadrant": quadrant
        }
        table_data.append(row_item)
        scatter_points.append({
            "x": vol,
            "y": share,
            "category": r["category"],
            "quadrant": quadrant
        })

    unit = res["unit"]
    chart_data = {
        "type": "scatter",
        "data": {
            "datasets": [
                {
                    "label": "상품군 포지셔닝",
                    "data": scatter_points,
                    "backgroundColor": "rgba(75, 192, 192, 0.8)",
                    "borderColor": "rgba(75, 192, 192, 1)",
                    "pointRadius": 6,
                    "pointHoverRadius": 9
                }
            ]
        },
        "options": {
            "responsive": True,
            "scales": {
                "x": {"title": {"display": True, "text": f"전체 거래 규모 ({unit})"}},
                "y": {"min": 0, "max": 100, "title": {"display": True, "text": "온라인몰 점유율 (%)"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] channel_dominance_matrix 완료 (상품군 수: {len(table_data)}, 소요: {elapsed}s)")

    return {
        "tool_name": "channel_dominance_matrix",
        "tool_title": "거래 규모 vs 온라인몰 점유율 4사분면 매트릭스 (산점도)",
        "reference_period": res["reference_period"],
        "unit": unit,
        "meta": {
            "median_volume": median_vol,
            "categories_count": len(table_data)
        },
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"{res['reference_period']} 기준 상품군별 거래액 규모와 온라인몰 점유율을 4사분면(대형/틈새 x 온라인/병행몰)으로 분류한 매트릭스입니다."
    }

# ==============================================================================
# 도구 10: channel_basket_composition (온라인몰 내 상품 구성비 vs 병행몰 내 상품 구성비)
# ==============================================================================
def channel_basket_composition(df, meta, reference_period=None, top_n=8, exclude_aggregates=True):
    """
    온라인몰 총매출 중 품목 구성비(%)와 온·오프라인 병행몰 총매출 중 품목 구성비(%)를 맞비교하는 포트폴리오 분석
    """
    start_time = time.time()
    res = channel_share_by_category(df, meta, reference_period, exclude_aggregates)
    t_data = res["table_data"]

    total_online = sum(r["pure_online_volume"] for r in t_data)
    total_omni = sum(r["omnichannel_volume"] for r in t_data)

    comp_list = []
    for r in t_data:
        on_share_in_basket = round((r["pure_online_volume"] / total_online) * 100, 2) if total_online > 0 else 0.0
        om_share_in_basket = round((r["omnichannel_volume"] / total_omni) * 100, 2) if total_omni > 0 else 0.0
        gap = round(on_share_in_basket - om_share_in_basket, 2)

        comp_list.append({
            "category": r["category"],
            "online_basket_share_pct": on_share_in_basket,
            "omnichannel_basket_share_pct": om_share_in_basket,
            "gap_pp": gap,
            "relative_importance": "온라인몰 집중 품목" if gap > 0 else ("병행몰 집중 품목" if gap < 0 else "균형")
        })

    # 전체 비중이 큰 순서대로 상위 N개 추출
    comp_list = sorted(comp_list, key=lambda x: max(x["online_basket_share_pct"], x["omnichannel_basket_share_pct"]), reverse=True)[:int(top_n)]

    labels = [r["category"] for r in comp_list]
    on_basket = [r["online_basket_share_pct"] for r in comp_list]
    om_basket = [r["omnichannel_basket_share_pct"] for r in comp_list]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "온라인몰 내 매출 비중 (%)",
                    "data": on_basket,
                    "backgroundColor": "rgba(54, 162, 235, 0.8)",
                    "borderWidth": 1
                },
                {
                    "label": "병행몰 내 매출 비중 (%)",
                    "data": om_basket,
                    "backgroundColor": "rgba(255, 99, 132, 0.8)",
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "indexAxis": "x",
            "scales": {
                "y": {"title": {"display": True, "text": "각 채널 내 구성비 (%)"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] channel_basket_composition 완료 (상위 {len(comp_list)}개, 소요: {elapsed}s)")

    return {
        "tool_name": "channel_basket_composition",
        "tool_title": "채널별 포트폴리오 바스켓 구성비 비교 (그룹 막대)",
        "reference_period": res["reference_period"],
        "unit": "%",
        "meta": {
            "total_online_volume": total_online,
            "total_omnichannel_volume": total_omni
        },
        "table_data": comp_list,
        "chart_data": chart_data,
        "summary": f"{res['reference_period']} 기준 순수 온라인몰과 병행몰 각각의 총매출 안에서 각 상품군이 차지하는 구성비(%) 차이 분석입니다."
    }

# ==============================================================================
# 도구 11: seasonal_channel_pattern (월별/분기별 특정 상품군 채널 계절성 분석)
# ==============================================================================
def seasonal_channel_pattern(df, meta, category=None, exclude_aggregates=True):
    """
    특정 상품군의 월별 평균 거래액 및 채널 선호 패턴(온라인몰 vs 병행몰)의 계절성 분석
    """
    start_time = time.time()
    det = meta.get("detected_columns", {})
    cat_col = det.get("category_col")
    op_col = det.get("operation_col")
    time_col = det.get("period_col")
    val_col = det.get("volume_col")
    unit = det.get("unit", "백만원")

    working_df = df.copy()
    if exclude_aggregates:
        agg_keywords = ["합계", "총계", "소계", "계", "전체"]
        cat_mask = (
            working_df[cat_col].astype(str).str.strip().isin(agg_keywords) |
            working_df[cat_col].astype(str).str.contains(r"^합계|^총계|\(계\)", regex=True)
        )
        op_mask = working_df[op_col].astype(str).str.strip().isin(agg_keywords)
        working_df = working_df[~(cat_mask | op_mask)]

    working_df["_std_channel"] = working_df[op_col].apply(_normalize_channel_name)

    available_cats = working_df[cat_col].dropna().unique().tolist()
    if not category or category not in available_cats:
        top_cat = working_df.groupby(cat_col)[val_col].sum().idxmax()
        category = str(top_cat)

    cat_df = working_df[working_df[cat_col].astype(str).str.strip() == str(category).strip()].copy()

    # 시점에서 월(Month) 추출 (예: 2024.03 -> 03월, 202403 -> 03월)
    def _extract_month(p_str):
        m = re.search(r'[\.\-\s\/]?(\d{1,2})$', str(p_str).strip())
        if m:
            return f"{int(m.group(1)):02d}월"
        return str(p_str).strip()

    cat_df["_month"] = cat_df[time_col].apply(_extract_month)

    # 월별 x 표준채널 평균 거래액 피벗
    pivot = cat_df.pivot_table(
        index="_month",
        columns="_std_channel",
        values=val_col,
        aggfunc="mean",
        fill_value=0.0
    ).reset_index()

    pivot = pivot.sort_values(by="_month")

    if "온라인몰" not in pivot.columns:
        pivot["온라인몰"] = 0.0
    if "온·오프라인 병행몰" not in pivot.columns:
        pivot["온·오프라인 병행몰"] = 0.0

    table_data = []
    for _, row in pivot.iterrows():
        on_v = round(float(row["온라인몰"]), 1)
        om_v = round(float(row["온·오프라인 병행몰"]), 1)
        tot = on_v + om_v
        on_pct = round((on_v / tot) * 100, 2) if tot > 0 else 0.0
        table_data.append({
            "month": str(row["_month"]),
            "category": category,
            "avg_online_volume": on_v,
            "avg_omnichannel_volume": om_v,
            "avg_total_volume": tot,
            "online_share_pct": on_pct
        })

    months = [r["month"] for r in table_data]
    on_vals = [r["avg_online_volume"] for r in table_data]
    om_vals = [r["avg_omnichannel_volume"] for r in table_data]

    chart_data = {
        "type": "line",
        "data": {
            "labels": months,
            "datasets": [
                {
                    "label": f"온라인몰 평균 거래액 ({unit})",
                    "data": on_vals,
                    "borderColor": "rgba(54, 162, 235, 1)",
                    "backgroundColor": "rgba(54, 162, 235, 0.15)",
                    "tension": 0.3
                },
                {
                    "label": f"온·오프라인 병행몰 평균 거래액 ({unit})",
                    "data": om_vals,
                    "borderColor": "rgba(255, 99, 132, 1)",
                    "backgroundColor": "rgba(255, 99, 132, 0.15)",
                    "tension": 0.3
                }
            ]
        },
        "options": {
            "responsive": True,
            "scales": {
                "y": {"title": {"display": True, "text": f"평균 거래액 ({unit})"}}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] seasonal_channel_pattern 완료 ({category}, 소요: {elapsed}s)")

    return {
        "tool_name": "seasonal_channel_pattern",
        "tool_title": f"'{category}' 월별 채널 선호 계절성 패턴 (평균 선 차트)",
        "reference_period": "전체 시점 월별 집계",
        "unit": unit,
        "meta": {"category": category, "months_count": len(table_data)},
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"'{category}' 품목의 월별 평균 거래액 및 채널 선호 계절성 패턴 분석입니다."
    }

# ==============================================================================
# 도구 12: single_category_deep_dive (선택 상품군 종합 360도 심층 대시보드)
# ==============================================================================
def single_category_deep_dive(df, meta, category=None, reference_period=None, exclude_aggregates=True):
    """
    선택한 1개 상품군의 거래 규모, 채널 점유율, 전체 시장 내 순위 및 비중 종합 분석 요약
    """
    start_time = time.time()
    res_share = channel_share_by_category(df, meta, reference_period, exclude_aggregates)
    t_data = res_share["table_data"]

    available_cats = [r["category"] for r in t_data]
    if not category or category not in available_cats:
        category = available_cats[0] if available_cats else ""

    target_item = next((r for r in t_data if r["category"] == category), None)
    if not target_item:
        return res_share

    total_market_vol = sum(r["total_volume"] for r in t_data)
    market_share_pct = round((target_item["total_volume"] / total_market_vol) * 100, 2) if total_market_vol > 0 else 0.0

    # 시장 내 순위 계산
    rank = 1
    for r in t_data:
        if r["total_volume"] > target_item["total_volume"]:
            rank += 1

    unit = res_share["unit"]
    table_data = [
        {"metric": "분석 대상 상품군", "value": category},
        {"metric": "기준 시점", "value": res_share["reference_period"]},
        {"metric": f"전체 거래액 ({unit})", "value": f"{target_item['total_volume']:,.0f}"},
        {"metric": "전체 이커머스 시장 내 매출 비중 (%)", "value": f"{market_share_pct}% (전체 {len(t_data)}개 중 {rank}위)"},
        {"metric": f"온라인몰 거래액 ({unit})", "value": f"{target_item['pure_online_volume']:,.0f} ({target_item['pure_online_share_pct']}%)"},
        {"metric": f"온·오프라인 병행몰 거래액 ({unit})", "value": f"{target_item['omnichannel_volume']:,.0f} ({target_item['omnichannel_share_pct']}%)"},
        {"metric": "지배 채널 판정", "value": target_item["dominant_channel"]}
    ]

    # 해당 품목의 채널 구성비 도넛 차트
    chart_data = {
        "type": "doughnut",
        "data": {
            "labels": ["온라인몰", "온·오프라인 병행몰"],
            "datasets": [
                {
                    "data": [target_item["pure_online_volume"], target_item["omnichannel_volume"]],
                    "backgroundColor": ["rgba(54, 162, 235, 0.85)", "rgba(255, 99, 132, 0.85)"],
                    "borderWidth": 2
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "legend": {"position": "bottom"}
            }
        }
    }

    elapsed = round(time.time() - start_time, 4)
    logger.info(f"[CALCULATE] single_category_deep_dive 완료 ({category}, 소요: {elapsed}s)")

    return {
        "tool_name": "single_category_deep_dive",
        "tool_title": f"'{category}' 360도 종합 심층 진단 대시보드",
        "reference_period": res_share["reference_period"],
        "unit": unit,
        "meta": {
            "category": category,
            "rank": rank,
            "total_categories": len(t_data),
            "market_share_pct": market_share_pct
        },
        "table_data": table_data,
        "chart_data": chart_data,
        "summary": f"'{category}' 상품군은 {res_share['reference_period']} 기준 전체 시장 {rank}위(점유율 {market_share_pct}%)이며, '{target_item['dominant_channel']}'이 지배적인 품목입니다."
    }
