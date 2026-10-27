/**
 * static/app.js - E-Commerce Channel Insight Analyzer
 * Vanilla JavaScript & Fetch API & Chart.js 연동 프론트엔드 컨트롤러
 */

document.addEventListener("DOMContentLoaded", () => {
    console.log("[PAGE] 페이지 초기 로딩 시작");

    let currentFile = null;
    let inspectionMeta = null;
    let currentChart = null;

    // DOM 요소 캐싱
    const statusDot = document.getElementById("statusDot");
    const serverModelText = document.getElementById("serverModelText");

    // Step 1 요소
    const rawFileSelect = document.getElementById("rawFileSelect");
    const refreshRawFilesBtn = document.getElementById("refreshRawFilesBtn");
    const inspectRawFileBtn = document.getElementById("inspectRawFileBtn");
    const dropzone = document.getElementById("dropzone");
    const csvFileInput = document.getElementById("csvFileInput");
    const selectedFileName = document.getElementById("selectedFileName");
    const inspectBtn = document.getElementById("inspectBtn");

    // Step 2 요소 (분석 대상 상품 선택 및 진단 아코디언)
    const diagnosisSection = document.getElementById("diagnosisSection");
    const categoryCountBadge = document.getElementById("categoryCountBadge");
    const categoryPillsGrid = document.getElementById("categoryPillsGrid");
    const toggleDiagMetaBtn = document.getElementById("toggleDiagMetaBtn");
    const diagMetaContent = document.getElementById("diagMetaContent");
    const diagMetaArrow = document.getElementById("diagMetaArrow");

    const diagFileName = document.getElementById("diagFileName");
    const diagEncoding = document.getElementById("diagEncoding");
    const diagSkippedRows = document.getElementById("diagSkippedRows");
    const diagCatCount = document.getElementById("diagCatCount");
    const diagOps = document.getElementById("diagOps");
    const diagRecPeriod = document.getElementById("diagRecPeriod");
    const warningsBox = document.getElementById("warningsBox");
    const warningsList = document.getElementById("warningsList");
    const previewThead = document.getElementById("previewThead");
    const previewTbody = document.getElementById("previewTbody");

    // Step 3 요소
    const suggestSection = document.getElementById("suggestSection");
    const nlQueryInput = document.getElementById("nlQueryInput");
    const nlQueryBtn = document.getElementById("nlQueryBtn");
    const nlAnswerBox = document.getElementById("nlAnswerBox");
    const nlMappedBadge = document.getElementById("nlMappedBadge");
    const nlAnswerText = document.getElementById("nlAnswerText");
    const queryChips = document.querySelectorAll(".query-chip");

    const getSuggestBtn = document.getElementById("getSuggestBtn");
    const suggestionsContainer = document.getElementById("suggestionsContainer");
    const suggestionCards = document.getElementById("suggestionCards");
    const toolSelect = document.getElementById("toolSelect");
    const periodParamGroup = document.getElementById("periodParamGroup");
    const periodSelect = document.getElementById("periodSelect");
    const rangePeriodParamGroup = document.getElementById("rangePeriodParamGroup");
    const startPeriodSelect = document.getElementById("startPeriodSelect");
    const endPeriodSelect = document.getElementById("endPeriodSelect");
    const categorySelect = document.getElementById("categorySelect");
    const categoryParamGroup = document.getElementById("categoryParamGroup");
    const runToolBtn = document.getElementById("runToolBtn");

    // Step 4 요소
    const resultsSection = document.getElementById("resultsSection");
    const resultToolTitle = document.getElementById("resultToolTitle");
    const resultSummaryText = document.getElementById("resultSummaryText");
    const resultBadges = document.getElementById("resultBadges");
    const mainChartCanvas = document.getElementById("mainChart");
    const resultThead = document.getElementById("resultThead");
    const resultTbody = document.getElementById("resultTbody");

    // Step 5 요소
    const explainSection = document.getElementById("explainSection");
    const generateReportBtn = document.getElementById("generateReportBtn");
    const reportContainer = document.getElementById("reportContainer");
    const reportModeBadge = document.getElementById("reportModeBadge");
    const reportModelBadge = document.getElementById("reportModelBadge");
    const reportMarkdownBody = document.getElementById("reportMarkdownBody");
    const modeBCard = document.getElementById("modeBCard");
    const modeACard = document.getElementById("modeACard");

    // =========================================================================
    // 1. 초기 서버 상태 확인 (GET /health)
    // =========================================================================
    async function checkServerHealth() {
        try {
            const res = await fetch("/health");
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            statusDot.classList.add("online");
            const keyText = data.api_key_configured ? "API Key 연결됨" : "Key 미설정(Fallback)";
            serverModelText.textContent = `${data.gemini_model} (${keyText})`;
            console.log(`[PAGE] 서버 헬스체크 성공: 모델=${data.gemini_model}, Key=${data.api_key_configured}`);
        } catch (err) {
            console.error(`[ERROR] 서버 헬스체크 실패: ${err.message}`);
            serverModelText.textContent = "서버 연결 불가";
        }
    }
    checkServerHealth();

    // =========================================================================
    // 2. raw_data 폴더 내 CSV 파일 목록 조회 (/api/raw-files)
    // =========================================================================
    async function loadRawFileList() {
        try {
            rawFileSelect.innerHTML = '<option value="">폴더 목록 조회 중...</option>';
            const res = await fetch("/api/raw-files");
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            rawFileSelect.innerHTML = "";
            if (!data.files || data.files.length === 0) {
                const opt = document.createElement("option");
                opt.value = "";
                opt.textContent = "⚠️ raw_data 폴더에 CSV 파일이 없습니다.";
                rawFileSelect.appendChild(opt);
                inspectRawFileBtn.disabled = true;
                return;
            }

            data.files.forEach((f, idx) => {
                const opt = document.createElement("option");
                opt.value = f.name;
                opt.textContent = `📄 ${f.name} (${f.size_formatted}, ${f.modified})`;
                if (idx === 0) opt.selected = true;
                rawFileSelect.appendChild(opt);
            });

            inspectRawFileBtn.disabled = false;
            console.log(`[PAGE] raw_data 폴더 파일 ${data.files.length}개 로드 완료`);
        } catch (err) {
            console.error(`[ERROR] raw_data 목록 조회 실패: ${err.message}`);
            rawFileSelect.innerHTML = '<option value="">목록 조회 실패</option>';
            inspectRawFileBtn.disabled = true;
        }
    }
    loadRawFileList();

    if (refreshRawFilesBtn) {
        refreshRawFilesBtn.addEventListener("click", () => {
            console.log("[PAGE] raw_data 폴더 파일 새로고침 요청");
            loadRawFileList();
        });
    }

    if (inspectRawFileBtn) {
        inspectRawFileBtn.addEventListener("click", async () => {
            const selectedFile = rawFileSelect.value;
            if (!selectedFile) {
                alert("분석할 CSV 파일을 선택해주세요.");
                return;
            }

            inspectRawFileBtn.disabled = true;
            inspectRawFileBtn.innerHTML = "<span>데이터 진단 중...</span>";
            console.log(`[INSPECT] raw_data 폴더 파일 직접 진단 요청 시작 (${selectedFile})`);

            try {
                const res = await fetch("/inspect-from-folder", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ file_name: selectedFile })
                });

                const data = await res.json();
                if (!res.ok || data.status !== "success") {
                    throw new Error(data.message || "파일 진단에 실패했습니다.");
                }

                applyInspectionResults(data);
                console.log(`[INSPECT] raw_data 폴더 파일 진단 완료: ${selectedFile}`);

            } catch (err) {
                console.error(`[ERROR] raw_data 파일 진단 실패: ${err.message}`);
                alert(`진단 오류: ${err.message}`);
            } finally {
                inspectRawFileBtn.disabled = false;
                inspectRawFileBtn.innerHTML = "⚡ 이 파일로 바로 분석";
            }
        });
    }

    // =========================================================================
    // 3. Step 1: 파일 드래그 앤 드롭 및 수동 업로드
    // =========================================================================
    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("dragover");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });

    csvFileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFileSelection(e.target.files[0]);
        }
    });

    function handleFileSelection(file) {
        if (!file.name.toLowerCase().endsWith(".csv")) {
            alert(".csv 확장자의 파일만 업로드할 수 있습니다.");
            return;
        }
        currentFile = file;
        const sizeKb = (file.size / 1024).toFixed(1);
        selectedFileName.textContent = `선택된 파일: ${file.name} (${sizeKb} KB)`;
        inspectBtn.disabled = false;
        console.log(`[UPLOAD] 파일 선택 완료: ${file.name} (${sizeKb} KB)`);
    }

    // =========================================================================
    // 4. Step 1 -> Step 2: 업로드 데이터셋 진단 요청 (POST /inspect)
    // =========================================================================
    inspectBtn.addEventListener("click", async () => {
        if (!currentFile) return;

        inspectBtn.disabled = true;
        inspectBtn.innerHTML = "<span>데이터 진단 분석 중...</span>";
        console.log(`[INSPECT] CSV 구조 진단 요청 시작 (${currentFile.name})`);

        const formData = new FormData();
        formData.append("file", currentFile);

        try {
            const res = await fetch("/inspect", {
                method: "POST",
                body: formData
            });

            const data = await res.json();
            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "CSV 진단에 실패했습니다.");
            }

            applyInspectionResults(data);

        } catch (err) {
            console.error(`[ERROR] CSV 구조 진단 실패: ${err.message}`);
            alert(`진단 오류: ${err.message}`);
        } finally {
            inspectBtn.disabled = false;
            inspectBtn.innerHTML = "<span>업로드한 파일 진단하기 (/inspect)</span>";
        }
    });

    const CATEGORY_ICONS = {
        "화장품": "💄",
        "가전·전자·통신기기": "📱",
        "의복": "👗",
        "음·식료품": "🍱",
        "컴퓨터 및 주변기기": "💻",
        "여행 및 교통서비스": "✈️",
        "음식서비스": "🛵",
        "생활용품": "🧴",
        "스포츠·레저용품": "⚽",
        "자동차 및 자동차용품": "🚗",
        "가구": "🛋️",
        "신발": "👟",
        "가방": "👜",
        "패션용품 및 액세서리": "💍",
        "아동·유아용품": "🍼",
        "애완용품": "🐶",
        "서적": "📚",
        "사무·문구": "✏️",
        "농축수산물": "🍎",
        "이쿠폰서비스": "🎟️",
        "문화 및 레저서비스": "🎬",
        "기타서비스": "🛎️",
        "기타": "📦"
    };

    function applyInspectionResults(data) {
        inspectionMeta = data;
        renderInspectionResults(data);

        // Step 2 상단 타원 버튼 렌더링
        if (categoryCountBadge) {
            categoryCountBadge.textContent = `총 ${data.categories.total_count}개 상품군`;
        }
        const defaultCat = data.categories.analyzable_list[0] || "";
        renderCategoryPills(data.categories.analyzable_list, defaultCat);

        diagnosisSection.classList.remove("hidden");
        suggestSection.classList.remove("hidden");
        populateSelectOptions(data);

        console.log(`[INSPECT] CSV 구조 진단 완료: 파일=${data.file_info.file_name}, 상품군=${data.categories.total_count}개, 운영형태=${data.operation_types.analyzable_list.join(", ")}, 시점=${data.periods.total_count}개`);
        diagnosisSection.scrollIntoView({ behavior: "smooth" });
    }

    function renderCategoryPills(categories, activeCat) {
        if (!categoryPillsGrid) return;
        categoryPillsGrid.innerHTML = "";

        categories.forEach(cat => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "category-pill" + (cat === activeCat ? " active" : "");
            btn.dataset.category = cat;

            const icon = CATEGORY_ICONS[cat] || "🏷️";
            btn.innerHTML = `<span class="pill-icon">${icon}</span><span class="pill-name">${cat}</span>`;

            btn.addEventListener("click", () => {
                selectAndAnalyzeCategory(cat);
            });

            categoryPillsGrid.appendChild(btn);
        });
    }

    function selectAndAnalyzeCategory(categoryName) {
        // 1. 타원 버튼 활성화 상태 갱신
        const allPills = categoryPillsGrid.querySelectorAll(".category-pill");
        allPills.forEach(p => p.classList.toggle("active", p.dataset.category === categoryName));

        // 2. Step 3 드롭다운 동기화
        if (categorySelect) {
            categorySelect.value = categoryName;
        }

        // 3. 분석 도구 자동 선택: 기간별 상품군 추이(13번) 또는 상품군 대상 도구
        let targetTool = toolSelect.value;
        const catSupportedTools = [
            "period_category_channel_trend",
            "category_channel_trend",
            "single_category_deep_dive",
            "seasonal_channel_pattern"
        ];

        if (!catSupportedTools.includes(targetTool)) {
            targetTool = "period_category_channel_trend";
            toolSelect.value = targetTool;
        }
        updateParamVisibility();

        const params = {
            category: categoryName,
            reference_period: periodSelect ? periodSelect.value : "",
            start_period: startPeriodSelect ? startPeriodSelect.value : "",
            end_period: endPeriodSelect ? endPeriodSelect.value : "",
            base_period: startPeriodSelect ? startPeriodSelect.value : "",
            target_period: endPeriodSelect ? endPeriodSelect.value : "",
            exclude_aggregates: true
        };

        console.log(`[CATEGORY-PILL] 타원 버튼 클릭: '${categoryName}' -> '${targetTool}' 분석 즉시 실행`);
        executeAnalysis(targetTool, params);
    }

    function renderInspectionResults(data) {
        diagFileName.textContent = `${data.file_info.file_name} (${data.file_info.file_size_formatted})`;
        diagEncoding.textContent = data.encoding_info.detected_encoding.toUpperCase();
        diagSkippedRows.textContent = `${data.encoding_info.skipped_rows}행 건너뜀`;
        diagCatCount.textContent = `${data.categories.total_count}개 품목`;
        diagOps.textContent = data.operation_types.analyzable_list.join(" vs ");
        diagRecPeriod.textContent = data.recommended_period || "최근 시점";

        warningsList.innerHTML = "";
        if (data.warnings && data.warnings.length > 0) {
            data.warnings.forEach(w => {
                const li = document.createElement("li");
                li.textContent = w;
                warningsList.appendChild(li);
            });
            warningsBox.classList.remove("hidden");
        } else {
            warningsBox.classList.add("hidden");
        }

        renderPreviewTable(data.preview_rows);
    }

    function renderPreviewTable(rows) {
        previewThead.innerHTML = "";
        previewTbody.innerHTML = "";
        if (!rows || rows.length === 0) return;

        const cols = Object.keys(rows[0]);
        const trHead = document.createElement("tr");
        cols.forEach(c => {
            const th = document.createElement("th");
            th.textContent = c;
            trHead.appendChild(th);
        });
        previewThead.appendChild(trHead);

        rows.forEach(r => {
            const tr = document.createElement("tr");
            cols.forEach(c => {
                const td = document.createElement("td");
                const val = r[c];
                td.textContent = (typeof val === "number") ? val.toLocaleString() : (val ?? "");
                tr.appendChild(td);
            });
            previewTbody.appendChild(tr);
        });
    }

    if (toggleDiagMetaBtn && diagMetaContent) {
        toggleDiagMetaBtn.addEventListener("click", () => {
            const isHidden = diagMetaContent.classList.toggle("hidden");
            if (diagMetaArrow) diagMetaArrow.textContent = isHidden ? "▼" : "▲";
        });
    }

    function populateSelectOptions(data) {
        const periods = data.periods.all_list;
        const rec = data.recommended_period;

        // 1. 단일 기준 시점
        periodSelect.innerHTML = "";
        periods.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p;
            opt.textContent = p;
            if (p === rec) opt.selected = true;
            periodSelect.appendChild(opt);
        });

        // 2. 기간 범위 (시작 / 종료 시점)
        startPeriodSelect.innerHTML = "";
        endPeriodSelect.innerHTML = "";

        // 시작 시점 기본값: 최근 24개월 전 또는 첫 번째 시점
        const defaultStartIdx = periods.length >= 24 ? periods.length - 24 : 0;
        const defaultStart = periods[defaultStartIdx];

        periods.forEach((p, idx) => {
            const optStart = document.createElement("option");
            optStart.value = p;
            optStart.textContent = p;
            if (p === defaultStart) optStart.selected = true;
            startPeriodSelect.appendChild(optStart);

            const optEnd = document.createElement("option");
            optEnd.value = p;
            optEnd.textContent = p;
            if (p === rec) optEnd.selected = true;
            endPeriodSelect.appendChild(optEnd);
        });

        // 3. 상품군
        categorySelect.innerHTML = "";
        data.categories.analyzable_list.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c;
            opt.textContent = c;
            categorySelect.appendChild(opt);
        });

        updateParamVisibility();
    }

    function updateParamVisibility() {
        const val = toolSelect.value;
        const rangeTools = [
            "period_category_channel_trend",
            "period_product_channel_behavior",
            "channel_share_shift",
            "growth_rate_by_channel"
        ];
        const categoryTools = [
            "category_channel_trend",
            "seasonal_channel_pattern",
            "single_category_deep_dive",
            "period_category_channel_trend"
        ];

        const isRange = rangeTools.includes(val);
        const needsCategory = categoryTools.includes(val);

        if (rangePeriodParamGroup) rangePeriodParamGroup.classList.toggle("hidden", !isRange);
        if (periodParamGroup) periodParamGroup.classList.toggle("hidden", isRange);
        if (categoryParamGroup) categoryParamGroup.classList.toggle("hidden", !needsCategory);
    }

    toolSelect.addEventListener("change", updateParamVisibility);

    // =========================================================================
    // 4. Step 3 신규: AI 자연어 데이터 질문하기 (POST /ask)
    // =========================================================================
    async function handleNaturalLanguageQuery(queryText) {
        const q = (queryText || nlQueryInput.value || "").trim();
        if (!q) {
            alert("질문 내용을 입력해주세요.");
            return;
        }

        nlQueryBtn.disabled = true;
        nlQueryBtn.innerHTML = "<span>🤖 의도 분석 & 계산 중...</span>";
        console.log(`[ASK] AI 자연어 질문 요청: "${q}"`);

        try {
            const res = await fetch("/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: q })
            });

            const data = await res.json();
            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "질문 처리 중 오류 발생");
            }

            console.log(`[ASK] AI 자연어 질문 응답 수신: 도구=${data.mapped_tool}, 답변 요약=${data.answer}`);

            // 답변 박스 렌더링
            nlMappedBadge.textContent = `실행 도구: ${data.tool_title}`;
            nlAnswerText.innerHTML = window.marked ? window.marked.parse(data.answer) : data.answer;
            nlAnswerBox.classList.remove("hidden");

            // 계산 결과(차트 & 테이블) Step 4에 렌더링
            if (data.result) {
                renderResults(data.result);
                resultsSection.classList.remove("hidden");
                explainSection.classList.remove("hidden");
            }

        } catch (err) {
            console.error(`[ERROR] AI 자연어 질문 실패: ${err.message}`);
            alert(`질문 오류: ${err.message}`);
        } finally {
            nlQueryBtn.disabled = false;
            nlQueryBtn.innerHTML = "<span>질문하기</span>";
        }
    }

    nlQueryBtn.addEventListener("click", () => handleNaturalLanguageQuery());
    nlQueryInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            handleNaturalLanguageQuery();
        }
    });

    // 추천 질문 칩 클릭 이벤트
    queryChips.forEach(chip => {
        chip.addEventListener("click", () => {
            const query = chip.getAttribute("data-query");
            nlQueryInput.value = query;
            handleNaturalLanguageQuery(query);
        });
    });

    // =========================================================================
    // 5. Step 3: Gemini AI 분석 도구 제안 요청 (POST /suggest)
    // =========================================================================
    getSuggestBtn.addEventListener("click", async () => {
        getSuggestBtn.disabled = true;
        getSuggestBtn.innerHTML = "<span>🤖 Gemini AI가 최적 분석을 추천 중...</span>";
        console.log("[SUGGEST] AI 분석 제안 요청 시작 (/suggest)");

        try {
            const res = await fetch("/suggest", { method: "POST" });
            const data = await res.json();
            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "도구 제안 수신 실패");
            }

            renderSuggestionCards(data.suggestions);
            suggestionsContainer.classList.remove("hidden");
            console.log(`[SUGGEST] AI 분석 제안 완료: ${data.suggestions.length}개 추천 도구 수신`);
            suggestionsContainer.scrollIntoView({ behavior: "smooth" });

        } catch (err) {
            console.error(`[ERROR] AI 분석 제안 실패: ${err.message}`);
            alert(`추천 오류: ${err.message}`);
        } finally {
            getSuggestBtn.disabled = false;
            getSuggestBtn.innerHTML = "<span>분석 추천 다시 받기 (/suggest)</span>";
        }
    });

    function renderSuggestionCards(suggestions) {
        suggestionCards.innerHTML = "";
        if (!suggestions || suggestions.length === 0) return;

        const toolTitles = {
            channel_share_by_category: "상품군별 채널 점유율 비교 (100% 누적 막대)",
            pure_online_dominance_top_n: "온라인몰 우세 상위 N개 상품군",
            omnichannel_dominance_top_n: "온·오프라인 병행몰 우세 상위 N개 상품군",
            macro_channel_ratio: "전체 거래액 채널 총 비중 (도넛 차트)",
            category_channel_trend: "특정 상품군 채널별 시계열 추이",
            channel_share_shift: "시점 간 병행몰 점유율 전이폭 (%p)",
            total_volume_ranking: "전체 거래액 상위 상품군 순위",
            growth_rate_by_channel: "채널별 거래액 성장률 비교",
            channel_dominance_matrix: "거래 규모 vs 점유율 4사분면 산점도",
            channel_basket_composition: "채널별 장바구니 바스켓 구성비",
            seasonal_channel_pattern: "월별 채널 선호 계절성 패턴",
            single_category_deep_dive: "특정 상품군 360도 심층 대시보드",
            period_category_channel_trend: "기간 범위별 상품군 채널 추이 & 점유율 변화",
            period_product_channel_behavior: "전 상품군 기간별 채널 선호 행태 비교 & 순위"
        };

        suggestions.forEach(s => {
            const card = document.createElement("div");
            card.className = "suggestion-card";
            const title = toolTitles[s.tool] || s.tool;

            card.innerHTML = `
                <div>
                    <div class="sugg-header">
                        <h4 class="sugg-title">${title}</h4>
                        <span class="sugg-period">${s.reference_period || "기준 시점"}</span>
                    </div>
                    <p class="sugg-why">💡 <strong>추천 이유:</strong> ${s.why || ""}</p>
                    ${s.caution ? `<p class="sugg-caution">⚠️ <strong>유의점:</strong> ${s.caution}</p>` : ""}
                </div>
                <button class="btn btn-primary btn-run-sugg" style="margin-top: 10px;">
                    <span>이 분석 바로 실행</span>
                </button>
            `;

            card.querySelector(".btn-run-sugg").addEventListener("click", () => {
                executeAnalysis(s.tool, s.params || {});
            });

            suggestionCards.appendChild(card);
        });
    }

    runToolBtn.addEventListener("click", () => {
        const toolName = toolSelect.value;
        const params = {
            reference_period: periodSelect.value,
            start_period: startPeriodSelect.value,
            end_period: endPeriodSelect.value,
            base_period: startPeriodSelect.value,
            target_period: endPeriodSelect.value,
            exclude_aggregates: true
        };

        if (!categoryParamGroup.classList.contains("hidden")) {
            params.category = categorySelect.value;
        }

        executeAnalysis(toolName, params);
    });

    // =========================================================================
    // 6. Step 4: 분석 실행 및 Chart.js / 결과 테이블 렌더링 (POST /run)
    // =========================================================================
    async function executeAnalysis(toolName, params) {
        console.log(`[RUN] 분석 실행 요청: 도구=${toolName}, 기준시점=${params.reference_period || "기본"}`);
        runToolBtn.disabled = true;
        runToolBtn.innerHTML = "<span>연산 중...</span>";

        try {
            const res = await fetch("/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ tool: toolName, params: params })
            });

            const data = await res.json();
            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "분석 실행 중 오류가 발생했습니다.");
            }

            const result = data.result;
            console.log(`[RUN] Pandas 계산 결과 수신 완료 (${result.tool_title})`);

            renderResults(result);

            resultsSection.classList.remove("hidden");
            explainSection.classList.remove("hidden");
            resultsSection.scrollIntoView({ behavior: "smooth" });

        } catch (err) {
            console.error(`[ERROR] 분석 도구 실행 실패: ${err.message}`);
            alert(`실행 오류: ${err.message}`);
        } finally {
            runToolBtn.disabled = false;
            runToolBtn.innerHTML = "<span>분석 실행 (/run)</span>";
        }
    }

    function renderResults(result) {
        resultToolTitle.textContent = result.tool_title;
        resultSummaryText.textContent = result.summary || "";

        resultBadges.innerHTML = `
            <span class="badge-tag">기준시점: ${result.reference_period}</span>
            <span class="badge-tag">단위: ${result.unit}</span>
            <span class="badge-tag">분석 행 수: ${result.meta.used_rows ?? result.meta.category_count ?? "-"}</span>
            <span class="badge-tag">합계 행 제외 필터링 적용</span>
        `;

        renderChart(result.chart_data);
        renderResultTable(result.table_data, result.unit);
    }

    function renderChart(chartConfig) {
        if (!chartConfig) return;

        if (currentChart) {
            currentChart.destroy();
            currentChart = null;
        }

        const ctx = mainChartCanvas.getContext("2d");
        const options = chartConfig.options || {};
        options.responsive = true;
        options.maintainAspectRatio = false;

        currentChart = new Chart(ctx, {
            type: chartConfig.type || "bar",
            data: chartConfig.data || {},
            options: options
        });

        const itemCount = (chartConfig.data && chartConfig.data.labels) ? chartConfig.data.labels.length : 0;
        console.log(`[CHART] Chart.js 렌더링 완료 (유형: ${chartConfig.type}, 렌더링된 항목 수: ${itemCount})`);
    }

    function renderResultTable(tableData, unit) {
        resultThead.innerHTML = "";
        resultTbody.innerHTML = "";
        if (!tableData || tableData.length === 0) return;

        const cols = Object.keys(tableData[0]);
        const trHead = document.createElement("tr");

        const colNamesMap = {
            category: "상품군",
            pure_online_volume: `온라인몰 거래액 (${unit})`,
            omnichannel_volume: `온·오프라인 병행몰 거래액 (${unit})`,
            total_volume: `총 거래액 (${unit})`,
            pure_online_share_pct: "온라인몰 점유율 (%)",
            omnichannel_share_pct: "병행몰 점유율 (%)",
            dominant_channel: "지배 채널",
            channel: "운영 채널",
            volume: `거래액 (${unit})`,
            share_pct: "비중 (%)",
            period: "시점",
            base_omnichannel_pct: "기준 점유율 (%)",
            target_omnichannel_pct: "비교 점유율 (%)",
            shift_pp: "점유율 변화폭 (%p)",
            trend: "추세",
            rank: "순위",
            pure_online_growth_pct: "온라인몰 성장률 (%)",
            omnichannel_growth_pct: "병행몰 성장률 (%)",
            growth_gap_pp: "성장률 격차 (%p)",
            faster_growing_channel: "더 빠른 성장 채널",
            quadrant: "4사분면 분류",
            online_basket_share_pct: "온라인몰 내 비중 (%)",
            omnichannel_basket_share_pct: "병행몰 내 비중 (%)",
            metric: "분석 지표",
            value: "지표 수치"
        };

        cols.forEach(c => {
            const th = document.createElement("th");
            th.textContent = colNamesMap[c] || c;
            trHead.appendChild(th);
        });
        resultThead.appendChild(trHead);

        tableData.forEach(r => {
            const tr = document.createElement("tr");
            cols.forEach(c => {
                const td = document.createElement("td");
                const val = r[c];
                if (typeof val === "number") {
                    td.textContent = val.toLocaleString();
                } else {
                    td.textContent = val ?? "";
                }
                tr.appendChild(td);
            });
            resultTbody.appendChild(tr);
        });
    }

    // =========================================================================
    // 7. Step 5: Gemini 유통 인사이트 리포트 생성 (POST /explain)
    // =========================================================================
    modeBCard.addEventListener("click", () => {
        modeBCard.classList.add("active");
        modeACard.classList.remove("active");
        modeBCard.querySelector("input").checked = true;
    });

    modeACard.addEventListener("click", () => {
        modeACard.classList.add("active");
        modeBCard.classList.remove("active");
        modeACard.querySelector("input").checked = true;
    });

    generateReportBtn.addEventListener("click", async () => {
        const selectedMode = document.querySelector('input[name="explainMode"]:checked').value;
        console.log(`[EXPLAIN] Gemini 인사이트 리포트 생성 요청 (모드: ${selectedMode})`);

        generateReportBtn.disabled = true;
        generateReportBtn.innerHTML = "<span>🤖 Gemini가 인사이트 리포트를 작성하고 있습니다...</span>";

        try {
            const res = await fetch("/explain", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mode: selectedMode })
            });

            const data = await res.json();
            if (!res.ok || data.status !== "success") {
                throw new Error(data.message || "리포트 생성 실패");
            }

            const rawMd = data.report_markdown;
            const htmlContent = window.marked ? window.marked.parse(rawMd) : rawMd.replace(/\n/g, "<br>");

            reportModeBadge.textContent = selectedMode === "B" ? "모드 B (정식 분석가 모드)" : "모드 A (비교용 허술한 모드)";
            reportModelBadge.textContent = `소요시간: ${data.ai_elapsed_seconds || 0}s | ${data.model || "Gemini"}`;
            reportMarkdownBody.innerHTML = htmlContent;

            reportContainer.classList.remove("hidden");
            console.log(`[EXPLAIN] Gemini 인사이트 리포트 생성 완료 (모드: ${selectedMode})`);
            reportContainer.scrollIntoView({ behavior: "smooth" });

        } catch (err) {
            console.error(`[ERROR] Gemini 리포트 생성 실패: ${err.message}`);
            alert(`리포트 생성 오류: ${err.message}`);
        } finally {
            generateReportBtn.disabled = false;
            generateReportBtn.innerHTML = "<span>📄 Gemini 인사이트 리포트 다시 생성하기</span>";
        }
    });

    console.log("[PAGE] 페이지 초기 로딩 완료 (자연어 질문 & 8대 콘솔 로그 완비)");
});
