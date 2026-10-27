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
with open("data/kosis_online_shopping_sample.csv", "rb") as f:
    csv_bytes = f.read()

res_inspect = client.post(
    "/inspect",
    data={"file": (io.BytesIO(csv_bytes), "kosis_online_shopping_sample.csv")},
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

print("\n>>> ALL 5 END-TO-END PIPELINE STEPS PASSED SUCCESSFULLY! <<<")
