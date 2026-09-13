# marathon-diet-coach

1206 상하이 풀마라톤 완주 + 식습관·훈련 분석 앱입니다.

입력은 Cursor 대화가 기본입니다. 먹은 것을 말로 알려 주거나 NRC 캡처를 채팅에 붙여 넣으면 기록하고, 앱 홈에서 칼로리·탄단지 비율·단것/폭식 시점·훈련량 적정도를 봅니다.

## 로컬 실행

1. 가상환경 생성 및 의존성 설치
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. 환경 변수 설정
   - `.env.example`를 복사해 `.env` 생성
3. 실행
   - `streamlit run app.py`

## Streamlit Cloud 배포

1. GitHub에 레포지토리 생성 후 코드 push
2. [Streamlit Community Cloud](https://share.streamlit.io/)에서 `New app` 선택
3. 아래 항목 입력
   - Repository: 본 레포지토리
   - Branch: `main`
   - Main file path: `app.py`
4. App settings > Secrets에 키 등록
   - `.streamlit/secrets.example.toml` 참고
5. Deploy

## 중요 보안 주의

- `.env`, `.streamlit/secrets.toml`, `*.numbers`, `data/`는 커밋하지 마세요.
- 키/개인 데이터는 Git에 올리지 말고 Secrets 또는 환경변수로만 관리하세요.
