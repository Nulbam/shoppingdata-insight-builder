# E-Commerce Channel Insight Analyzer (온라인몰 vs 병행몰 분석기)

통계청(KOSIS)의 **'온라인쇼핑몰 운영형태별/상품군별 거래액'** 데이터를 기반으로, **순수 온라인몰**과 **온·오프라인 병행몰(백화점몰/대형마트몰 등)**의 채널 경쟁력 및 지배력을 진단하고 Gemini 3.5 Flash Lite를 통해 데이터 기반 유통 전략 인사이트를 도출하는 풀스택 웹 애플리케이션입니다.

---

## 🌟 핵심 특징 (Key Highlights)

1. **KOSIS 데이터 자동 진단 (Smart Inspection)**
   - 4대 인코딩(`utf-8-sig`, `utf-8`, `cp949`, `euc-kr`) 자동 순차 감지 및 1행 메타 주석 스마트 건너뛰기
   - 이중 계산(Double-counting) 방지를 위한 **'합계/총계/계' 행 사전 분리 및 격리**
   - 상품군, 운영형태, 시점, 결측치 보정 등 **11대 진단 메타데이터** 즉각 제공

2. **AI 자연어 데이터 질문하기 (Q&A via Natural Language)**
   - *"화장품의 온라인몰 점유율은 얼마인가요?"*, *"온라인몰 1위 품목은?"* 등 일상어로 자유롭게 질문 가능
   - Gemini가 질문 의도를 분석하여 12개 정밀 분석 도구로 자동 라우팅 $\rightarrow$ Pandas가 확정 수치 계산 $\rightarrow$ Step 4 차트/테이블 실시간 동기화

3. **12대 정밀 채널 분석 도구 (Pandas 100% 무결성 엔진)**
   - 채널 점유율, 지배력 랭킹 Top-N, 거시 채널 비중, 시계열 추이, 기간별 점유율 변화폭(%p), 성장률, 4사분면 매트릭스, 단일 품목 심층 진단 등 제공
   - **AI 환각(Hallucination) 0% 원칙**: 모든 숫자 계산(합계, 점유율 %, 순위, 증감률)은 오직 Pandas가 확정하며 Gemini에게 계산을 절대 시키지 않습니다.

4. **인터랙티브 시각화 & 정밀 테이블 (Vanilla JS + Chart.js)**
   - 막대(Bar), 도넛(Doughnut), 꺾은선(Line), 산점도(Scatter) 인터랙티브 반응형 차트 지원
   - 집계 수치 및 점유율을 한눈에 확인할 수 있는 데이터 테이블 및 컬럼 정렬 기능

5. **Gemini 유통 전략가 심층 리포트 (Insight Report)**
   - **모드 A (자가 진단)**: 일반적 추정 분석 (비교용)
   - **모드 B (공식 리포트)**: Pandas가 계산을 완료한 확정 수치 테이블만 Gemini에 프롬프트로 전달하여 팩트 기반 유통 전략 리포트 마크다운 생성

---

## 🛠️ 기술 스택 (Tech Stack)

- **Backend**: Python 3.10+, Flask 3.x, Pandas 2.x/3.x, python-dotenv
- **Frontend**: Vanilla JavaScript (ES6+), Vanilla CSS, Chart.js (CDN)
- **AI Model**: Google Gemini API (`google-genai` SDK, `gemini-3.5-flash-lite`)
- **Architecture**: No-DB, No-Node.js, No-Docker, Zero-Heavy-Frameworks

---

## 📁 프로젝트 구조 (Project Structure)

```text
shoppingdata-insight-builder/
├── data/
│   └── kosis_online_shopping_sample.csv   # 테스트용 KOSIS 샘플 CSV (CP949 인코딩)
├── raw_data/                              # 사용자가 KOSIS 원본 CSV를 직접 넣는 전용 폴더
│   ├── kosis_sample_raw.csv               # 기본 제공 원본 샘플 CSV
│   └── 안내_여기에_CSV파일을_넣어주세요.txt
├── static/
│   ├── app.js                             # Vanilla JS 프론트엔드 통신 & 차트 렌더링
│   └── style.css                          # 모던 반응형 커스텀 CSS
├── templates/
│   └── index.html                         # 5단계 분석 대시보드 단일 페이지
├── .env.example                           # 환경변수 템플릿
├── .gitignore                             # API 키 및 가상환경 격리
├── app.py                                 # Flask 서버 및 Gemini / 라우팅 엔드포인트
├── requirements.txt                       # 최소 필수 의존성 목록
├── test_e2e.py                            # 7단계 파이프라인 E2E 자동 테스트
└── tools.py                               # 12대 정밀 분석 도구 Pandas 연산 모듈
```

---

## 🚀 빠른 시작 가이드 (Quick Start)

### 1. 저장소 클론 및 이동
```bash
git clone https://github.com/Nulbam/shoppingdata-insight-builder.git
cd shoppingdata-insight-builder
```

### 2. 가상환경 생성 및 활성화 (Windows 기준)
```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. 패키지 설치
```powershell
pip install -r requirements.txt
```

### 4. 환경 변수 설정 (.env)
루트 디렉터리에 `.env` 파일을 생성하고 발급받은 Google Gemini API Key를 입력합니다.
```ini
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
FLASK_DEBUG=True
MAX_CONTENT_LENGTH_MB=10
```

### 5. 애플리케이션 실행
```powershell
python app.py
```
브라우저에서 `http://127.0.0.1:5000`으로 접속합니다.

---

## 🧪 자동화 테스트 (End-to-End Test)

서버 헬스체크부터 CSV 진단, 도구 추천, Pandas 연산, AI 리포트 생성, 자연어 질문 답변까지 총 6단계 파이프라인 전체를 원클릭으로 검증합니다.

```powershell
.\venv\Scripts\python.exe test_e2e.py
```

---

## 🔒 데이터 보안 및 AI 격벽 원칙 (Integrity Architecture)

- **API 키 프론트엔드 비노출**: Gemini API Key는 백엔드 환경변수(`.env`)로만 엄격히 통제되며 프론트엔드로 전달되지 않습니다.
- **원본 CSV 비전송**: 원본 대용량 CSV는 브라우저 및 Gemini로 전송하지 않으며, 서버 메모리(Pandas) 내에서 안전하게 가공된 메타데이터 및 집계 수치만 전송합니다.
- **수치 무결성 보장**: Gemini는 "추천", "의도 라우팅", "비즈니스 문맥 해석"만을 담당하며, 모든 수치 연산은 오직 Pandas가 확정합니다.

---

## 📄 라이선스 (License)
MIT License
