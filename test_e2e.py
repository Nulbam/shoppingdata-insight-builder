import io
import sys
import json
from app import app

client = app.test_client()

print("=== [E2E STEP 1] Server Health Check ===")
res_health = client.get("/health")
assert res_health.status_code == 200, f"Health check failed: {res_health.status_code}"
health_data = res_health.get_json()
print("Health OK:", health_data)

print("\n=== [E2E STEP 2] CSV Upload & Inspection (/inspect) ===")
import os

target_csv_file = None
for search_dir in ["raw_data", "data"]:
    if os.path.exists(search_dir):
        csv_candidates = [f for f in os.listdir(search_dir) if f.lower().endswith(".csv")]
        if csv_candidates:
            target_csv_file = os.path.join(search_dir, csv_candidates[0])
            break

if not target_csv_file:
    raise FileNotFoundError("테스트할 CSV 파일이 raw_data 또는 data 폴더에 없습니다.")

print("Testing with CSV file:", target_csv_file)
with open(target_csv_file, "rb") as f:
    csv_bytes = f.read()

res_inspect = client.post(
    "/inspect",
    data={"file": (io.BytesIO(csv_bytes), os.path.basename(target_csv_file))},
    content_type="multipart/form-data"
)
assert res_inspect.status_code == 200, f"Inspect failed: {res_inspect.status_code}"
inspect_data = res_inspect.get_json()
print("Inspect Status:", inspect_data["status"])
print("Detected Encoding:", inspect_data["encoding_info"]["detected_encoding"])
print("Skipped Rows:", inspect_data["encoding_info"]["skipped_rows"])
print("Total Analyzable Categories:", inspect_data["categories"]["total_count"])
print("Recommended Period:", inspect_data["recommended_period"])
print("Warnings:", inspect_data["warnings"])

print("\n=== [E2E STEP 3] Gemini Tool Suggestion (/suggest) ===")
res_suggest = client.post("/suggest")
assert res_suggest.status_code == 200, f"Suggest failed: {res_suggest.status_code}"
suggest_data = res_suggest.get_json()
print("Suggest Status:", suggest_data["status"])
print("Suggest Source:", suggest_data.get("source"))
print("Model:", suggest_data.get("model"))
print("Suggestions Count:", len(suggest_data["suggestions"]))
for s in suggest_data["suggestions"]:
    tool = s["tool"]
    period = s.get("reference_period")
    why = s.get("why", "")[:45]
    print(f" - Tool: {tool} | Period: {period} | Why: {why}...")

print("\n=== [E2E STEP 4] Pandas Analysis Execution (/run) ===")
target_tool = suggest_data["suggestions"][0]["tool"]
target_params = suggest_data["suggestions"][0].get("params", {"reference_period": inspect_data["recommended_period"]})
res_run = client.post("/run", json={"tool": target_tool, "params": target_params})
assert res_run.status_code == 200, f"Run failed: {res_run.status_code}"
run_data = res_run.get_json()["result"]
print("Run Tool Title:", run_data["tool_title"])
print("Table Data Rows:", len(run_data["table_data"]))
print("Chart Type:", run_data["chart_data"]["type"])
print("Sample Row:", run_data["table_data"][0])

print("\n=== [E2E STEP 5] Gemini Insight Report Generation (/explain Mode B) ===")
res_explain = client.post("/explain", json={"mode": "B"})
assert res_explain.status_code == 200, f"Explain failed: {res_explain.status_code}"
explain_data = res_explain.get_json()
print("Explain Status:", explain_data["status"])
print("Explain Source:", explain_data.get("source"))
print("Report Preview:\n" + "="*50)
print(explain_data["report_markdown"][:600])
print("="*50)

print("\n=== [E2E STEP 6] AI Natural Language Data Query (/ask) ===")
res_ask = client.post("/ask", json={"query": "온라인몰 점유율이 가장 높은 품목은?"})
assert res_ask.status_code == 200, f"Ask failed: {res_ask.status_code}"
ask_data = res_ask.get_json()
print("Ask Status:", ask_data["status"])
print("Mapped Tool:", ask_data["mapped_tool"])
print("Answer:", ask_data["answer"])
print("Result rows:", len(ask_data["result"]["table_data"]))

print("\n=== [E2E STEP 7] Direct raw_data Folder File Inspection (/inspect-from-folder) ===")
res_raw_list = client.get("/api/raw-files")
assert res_raw_list.status_code == 200, f"Raw files list failed: {res_raw_list.status_code}"
raw_list_data = res_raw_list.get_json()
print("raw_data folder files count:", raw_list_data["count"])
assert raw_list_data["count"] >= 1, "raw_data folder should contain at least 1 file"
target_raw_file = raw_list_data["files"][0]["name"]

res_folder_inspect = client.post("/inspect-from-folder", json={"file_name": target_raw_file})
assert res_folder_inspect.status_code == 200, f"Folder inspect failed: {res_folder_inspect.status_code}"
folder_inspect_data = res_folder_inspect.get_json()
print("Folder inspect status:", folder_inspect_data["status"])
print("Folder inspect file:", folder_inspect_data["file_info"]["file_name"])
print("Detected categories:", folder_inspect_data["categories"]["total_count"])

print("\n=== [E2E STEP 8] Period & Product Channel Behavior Analysis (Tool 13, Tool 14) ===")
# 8-1. Tool 13 실행 테스트
res_tool13 = client.post("/run", json={
    "tool": "period_category_channel_trend",
    "params": {
        "category": "화장품",
        "start_period": "2023.01",
        "end_period": "2026.08"
    }
})
assert res_tool13.status_code == 200, f"Tool 13 failed: {res_tool13.status_code}"
t13_data = res_tool13.get_json()["result"]
print("Tool 13 Title:", t13_data["tool_title"])
print("Tool 13 Periods Analyzed:", t13_data["meta"]["periods_count"])
print("Tool 13 Summary:", t13_data["summary"][:60], "...")

# 8-2. Tool 14 실행 테스트
res_tool14 = client.post("/run", json={
    "tool": "period_product_channel_behavior",
    "params": {
        "start_period": "2020.01",
        "end_period": "2026.08"
    }
})
assert res_tool14.status_code == 200, f"Tool 14 failed: {res_tool14.status_code}"
t14_data = res_tool14.get_json()["result"]
print("Tool 14 Title:", t14_data["tool_title"])
print("Tool 14 Total Categories:", t14_data["meta"]["total_categories"])
print("Top Online Shift:", t14_data["meta"]["top_online_category"], f"+{t14_data['meta']['top_online_shift']}%p")

# 8-3. AI 자연어 질문을 통한 기간별 행태 자동 라우팅 테스트
res_ask_period = client.post("/ask", json={"query": "2020년부터 2026년까지 화장품의 기간별 채널 행태 변화는?"})
assert res_ask_period.status_code == 200, f"Ask period failed: {res_ask_period.status_code}"
ask_period_data = res_ask_period.get_json()
print("Ask Period Mapped Tool:", ask_period_data["mapped_tool"])
print("Ask Period Answer:", ask_period_data["answer"][:80], "...")

print("\n>>> ALL 8 END-TO-END PIPELINE STEPS (INCLUDING PERIOD & PRODUCT BEHAVIOR) PASSED SUCCESSFULLY! <<<")
