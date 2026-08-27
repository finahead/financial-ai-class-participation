# 배포 체크리스트

## 1. 새 GitHub 저장소 만들기
권장 저장소명:
financial-ai-class-participation

- Public 저장소로 만들어도 됩니다.
- 실제 비밀번호/API 키는 GitHub에 올리지 않습니다.

## 2. 업로드할 파일
아래 파일/폴더를 저장소 최상위에 업로드합니다.

- app.py
- requirements.txt
- README.md
- DEPLOY_CHECKLIST.md
- .gitignore
- .streamlit/secrets.toml.example  (참고용, 실제 비밀번호 없음)

## 3. Streamlit Community Cloud에서 새 앱 만들기
- Repository: 새로 만든 저장소
- Branch: main
- Main file path: app.py
- Python: 3.11 권장
- App URL 예시: ai-class-sb.streamlit.app

## 4. Secrets 설정
Streamlit 앱 설정 > Secrets에 아래 두 줄 입력:

APP_PASSWORD = "sbi2026"
ADMIN_PASSWORD = "별도의 관리자 비밀번호"

교육생에게는 APP_PASSWORD만 안내합니다.

## 5. 접속 테스트
참여자:
https://<앱주소>.streamlit.app

관리자:
https://<앱주소>.streamlit.app/?view=admin

## 6. 수업 전 확인
- 닉네임 등록 가능
- 관리자 화면 접속 가능
- 사례 1 선택 후 '응답 받기' 체크
- '현재 질문 적용' 클릭
- 다른 브라우저/휴대폰에서 질문 표시 확인
- 응답 후 실시간 집계 확인
- CSV 다운로드 확인

## 7. 수업 종료
관리자 화면에서 '전체 응답 CSV 다운로드' 후 보관합니다.

주의:
현재 버전은 `/tmp` SQLite DB를 사용하므로 앱 재시작 시 응답이 사라질 수 있습니다.
