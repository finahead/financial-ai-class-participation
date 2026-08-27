# 금융 AI 사례 & 규제대응 참여형 앱

20명 내외의 교육생이 사례 설명 전에 사전 판단을 제출하고,
진행자가 실시간 응답 분포를 확인하기 위한 Streamlit 앱입니다.

## 주요 기능
- 참여자 닉네임 등록
- 사례 1~6 사전/사후 질문
- 실시간 응답 집계
- 참여자 결과 공개/비공개
- 진행자 전용 관리 화면
- 전체 응답 CSV 다운로드
- 응답/참여자 초기화

## 참여자 주소
배포 후 생성된 기본 Streamlit URL을 사용합니다.

예:
https://ai-class-sb.streamlit.app

## 진행자 주소
기본 주소 뒤에 `?view=admin`을 붙입니다.

예:
https://ai-class-sb.streamlit.app/?view=admin

## Streamlit Secrets
GitHub에는 실제 비밀번호를 올리지 마세요.
Streamlit Community Cloud의 App settings > Secrets에 아래 형식으로 입력합니다.

APP_PASSWORD = "교육생 접속 비밀번호"
ADMIN_PASSWORD = "진행자 관리 비밀번호"

## 주의
현재 버전은 수업 1회용 경량 구조입니다.
응답은 Streamlit 실행 환경의 `/tmp` SQLite DB에 저장되므로,
앱이 재시작되면 응답 데이터가 초기화될 수 있습니다.
중요한 결과는 수업 종료 전에 관리자 화면에서 CSV로 다운로드하세요.
