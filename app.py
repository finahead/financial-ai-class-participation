
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from openai import OpenAI

DB_PATH = Path("/tmp/financial_ai_participation.db")

st.set_page_config(
    page_title="금융 AI 참여화면",
    page_icon="💬",
    layout="wide",
)


st.markdown(
    """
    <style>
      /* 노트북/프로젝터 화면에서 세로 공간을 절약 */
      .block-container {
          padding-top: 2.0rem;
          padding-bottom: 2.0rem;
          max-width: 1500px;
      }
      h1 { font-size: 2.35rem !important; }
      h2 { font-size: 1.85rem !important; }
      h3 { font-size: 1.35rem !important; }
      div[data-testid="stMetricValue"] {
          font-size: 1.7rem;
      }

      div[data-testid="stHorizontalBlock"] > div:last-child {
          align-self: flex-start;
      }

      @media (max-width: 1100px) {
          .block-container {
              padding-left: 1.5rem;
              padding-right: 1.5rem;
          }
          h1 { font-size: 2.0rem !important; }
          h2 { font-size: 1.6rem !important; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn


def init_db():
    with db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_case INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL DEFAULT 'pre',
                display_mode TEXT NOT NULL DEFAULT 'waiting',
                updated_at TEXT NOT NULL
            )
        """)

        # v1에서 만들어진 기존 SQLite DB가 남아 있을 수 있으므로
        # INSERT보다 먼저 스키마를 현재 버전에 맞춘다.
        # Streamlit에서는 여러 브라우저 세션이 동시에 시작될 수 있어
        # 두 세션이 동시에 같은 컬럼을 추가하려는 race condition이 발생할 수 있다.
        # 각 ALTER TABLE을 개별적으로 시도하고, 이미 추가된 컬럼이면 안전하게 무시한다.
        def ensure_column(column_name, column_sql):
            cols_now = [r[1] for r in conn.execute("PRAGMA table_info(app_state)").fetchall()]
            if column_name in cols_now:
                return
            try:
                conn.execute(f"ALTER TABLE app_state ADD COLUMN {column_sql}")
                conn.commit()
            except sqlite3.OperationalError as e:
                # 다른 세션이 직전에 같은 컬럼을 추가했으면 duplicate column 오류가 날 수 있음
                if "duplicate column name" not in str(e).lower():
                    raise

        ensure_column("display_mode", "display_mode TEXT NOT NULL DEFAULT 'waiting'")
        ensure_column("current_case", "current_case INTEGER NOT NULL DEFAULT 0")
        ensure_column("phase", "phase TEXT NOT NULL DEFAULT 'pre'")
        ensure_column("updated_at", "updated_at TEXT NOT NULL DEFAULT ''")

        conn.execute("""
            INSERT OR IGNORE INTO app_state
            (id, current_case, phase, display_mode, updated_at)
            VALUES (1, 0, 'pre', 'waiting', ?)
        """, (datetime.now().isoformat(timespec="seconds"),))

        # 기존 1번 상태행도 새 구조에 맞춰 기본값 보정
        conn.execute("""
            UPDATE app_state
            SET current_case = COALESCE(current_case, 0),
                phase = COALESCE(NULLIF(phase, ''), 'pre'),
                display_mode = COALESCE(NULLIF(display_mode, ''), 'waiting'),
                updated_at = CASE
                    WHEN updated_at IS NULL OR updated_at = ''
                    THEN ?
                    ELSE updated_at
                END
            WHERE id = 1
        """, (datetime.now().isoformat(timespec="seconds"),))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                nickname TEXT PRIMARY KEY,
                joined_at TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                nickname TEXT NOT NULL,
                case_id INTEGER NOT NULL,
                phase TEXT NOT NULL,
                answer TEXT NOT NULL,
                answered_at TEXT NOT NULL,
                PRIMARY KEY (nickname, case_id, phase)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exercise_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_exercise INTEGER NOT NULL DEFAULT 0,
                display_mode TEXT NOT NULL DEFAULT 'waiting',
                spotlight_nickname TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO exercise_state
            (id, current_exercise, display_mode, spotlight_nickname, updated_at)
            VALUES (1, 0, 'waiting', '', ?)
        """, (datetime.now().isoformat(timespec="seconds"),))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exercise_responses (
                nickname TEXT NOT NULL,
                exercise_id INTEGER NOT NULL,
                judgment TEXT NOT NULL,
                reason TEXT NOT NULL,
                procedure TEXT NOT NULL,
                answered_at TEXT NOT NULL,
                PRIMARY KEY (nickname, exercise_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS confirmation_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                display_mode TEXT NOT NULL DEFAULT 'waiting',
                spotlight_nickname TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO confirmation_state
            (id, display_mode, spotlight_nickname, updated_at)
            VALUES (1, 'waiting', '', ?)
        """, (datetime.now().isoformat(timespec="seconds"),))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS confirmation_responses (
                nickname TEXT PRIMARY KEY,
                answer TEXT NOT NULL,
                answered_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS confirmation_ai_reviews (
                nickname TEXT PRIMARY KEY,
                answer_hash TEXT NOT NULL,
                review_text TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            )
        """)
        conn.commit()


CASES = {
    1: {
        "title": "사례 1 · 금융이력 부족자를 위한 AI 대안신용평가",
        "question": "금융이력이 부족해 AI 점수가 낮게 나온 고객의 대출한도를 자동으로 낮춰도 된다고 생각하십니까?",
        "options": ["그렇다", "조건부로 가능하다", "자동으로 낮추면 안 된다", "잘 모르겠다"],
        "focus": "데이터 부족과 실제 신용위험은 같은 의미인가?",
    },
    2: {
        "title": "사례 2 · FDS 기반 보이스피싱 대응",
        "question": "AI/FDS가 보이스피싱 고위험 거래로 판단하면 거래를 자동 차단해도 된다고 생각하십니까?",
        "options": ["즉시 자동 차단해야 한다", "조건에 따라 자동 차단할 수 있다", "사람 확인 후에만 차단해야 한다", "잘 모르겠다"],
        "focus": "탐지 신호와 최종 조치는 어디까지 자동화할 수 있는가?",
    },
    3: {
        "title": "사례 3 · 생성형 AI 상담요약",
        "question": "상담사가 AI가 만든 상담요약을 한 번 확인했다면 고객에게 그대로 보내도 충분하다고 생각하십니까?",
        "options": ["충분하다", "핵심항목만 추가 확인하면 된다", "원문·근거와 비교할 수 있는 통제가 더 필요하다", "잘 모르겠다"],
        "focus": "사람이 확인했다는 사실만으로 Human-in-the-loop가 성립하는가?",
    },
    4: {
        "title": "사례 4 · AI 코딩 에이전트",
        "question": "AI 코딩 에이전트가 수정한 코드가 모든 테스트를 통과했다면 운영환경에 배포해도 된다고 생각하십니까?",
        "options": ["배포해도 된다", "개발자 확인 후 배포할 수 있다", "별도 보안·변경·배포 통제가 더 필요하다", "잘 모르겠다"],
        "focus": "테스트 통과는 보안 적정성과 운영 배포 승인을 의미하는가?",
    },
    5: {
        "title": "사례 5 · AI OCR을 통한 보험금 신속지급",
        "question": "AI OCR 정확도가 99%라면 소액 보험금 청구는 사람 확인 없이 자동지급해도 된다고 생각하십니까?",
        "options": ["자동지급해도 된다", "일부 조건에서는 가능하다", "정확도만으로 자동지급을 결정하면 안 된다", "잘 모르겠다"],
        "focus": "문서 인식 정확도와 지급결정의 안전성은 같은 지표인가?",
    },
    6: {
        "title": "사례 6 · 생성형 AI 언더라이팅",
        "question": "AI가 특정 보장의 가입 제한 대상으로 판단하면 설계 단계에서 해당 보장을 자동 제외해도 된다고 생각하십니까?",
        "options": ["자동 제외해도 된다", "조건부로 가능하다", "추가 확인·심사 없이 자동 제외하면 안 된다", "잘 모르겠다"],
        "focus": "AI의 해석 결과와 고객 권리에 영향을 주는 최종 판단을 분리해야 하는가?",
    },
}



EXERCISES = {
    1: {
        "title": "상황별 실습 1",
        "question": "AI가 최종결정해도 되는 업무와 사람이 반드시 개입해야 하는 업무는 무엇인가?",
        "points": "대출한도·금리·상품추천·거래차단·상담기록·운영배포를 영향도별로 구분해 보세요.",
        "hint": "고객 권리·금전거래·운영시스템에 미치는 영향을 기준으로 판단합니다.",
    },
    2: {
        "title": "상황별 실습 2",
        "question": "AI OCR 오류로 고객 B의 대출이 거절됐다면 누구 책임이며 어떤 절차가 필요했는가?",
        "points": "입사일 오인식, 자동거절 후보, 원본 서류 확인 여부를 중심으로 답하세요.",
        "hint": "AI가 읽지 못한 것과 고객이 자격이 없는 것은 다른 문제입니다.",
    },
    3: {
        "title": "상황별 실습 3",
        "question": "고객 C에게 자사 중금리대출을 1순위로 추천한 것은 잘못인가?",
        "points": "고객에게 가장 유리한 추천, 승인 가능성, 자사상품 우대, 광고와 추천 구분을 검토하세요.",
        "hint": "추천 목표가 무엇인지가 핵심입니다.",
    },
    4: {
        "title": "상황별 실습 4",
        "question": "고객 D의 보이스피싱 의심거래를 AI가 자동 차단해도 되는가?",
        "points": "정상 인증이 완료된 거래, 외부 의심정보, 거래지연·추가인증·차단 단계를 나눠 보세요.",
        "hint": "AI 판단과 실제 조치수준을 구분합니다.",
    },
    5: {
        "title": "상황별 실습 5",
        "question": "직원이 AI 상담요약을 확인했다면 충분한 통제가 이루어진 것인가?",
        "points": "자동화 편향, 원문 근거 연결, 무수정 승인율, 고위험 발언 누락을 중심으로 답하세요.",
        "hint": "사람이 있는 것과 사람이 오류를 발견할 수 있는 것은 다릅니다.",
    },
    6: {
        "title": "상황별 실습 6",
        "question": "개발자가 AI 코딩 에이전트가 만든 코드를 검토했다면 배포해도 되는가?",
        "points": "인증 코드 변경, 테스트 통과, 코드리뷰, 정적분석, 배포승인을 구분하세요.",
        "hint": "AI가 만든 코드도 기존 변경관리 절차를 통과해야 합니다.",
    },
}



CONFIRMATION_LAB = {
    "title": "마지막 실습 · FSS IT검사 확인서 작성",
    "scenario": (
        "○○은행은 고객 거래내역을 AI가 분석하여 우대금리 조건 충족 여부를 자동 판정하는 시스템을 "
        "2026년 4월부터 운영하였다. 고객 거래정보 → AI가 급여이체·카드사용·자동이체 등 우대조건 판단 "
        "→ 우대금리 코드 생성 → 이자계산 배치시스템 반영 → 고객계좌 이자 지급 구조이다. "
        "2026년 7월 고객 민원을 계기로 점검한 결과, AI가 거래 적요에 '급여'라는 문구가 포함된 일부 "
        "개인 간 송금을 실제 급여이체로 오분류한 사실이 확인되었다."
    ),
    "impact": (
        "그 결과 1,240명에게 우대금리가 과다 적용되어 총 2,800만원이 과다 지급되었고, "
        "318명에게는 우대금리가 적용되지 않아 총 940만원이 과소 지급되었다."
    ),
    "facts": [
        "운영 전 테스트 대상은 50명의 고객 사례에 한정",
        "개인 간 송금 등 예외·경계사례 테스트 미실시",
        "2026년 5월 외부업체가 AI 판정 Prompt를 변경",
        "Prompt 변경에 대한 내부 변경요청·책임자 승인·재테스트 기록 없음",
        "AI 판정결과가 별도 검증절차 없이 이자계산 배치에 직접 반영",
        "사후 검증은 고객별 대사가 아닌 전체 이자지급액 합계만 확인",
        "운영 이후 AI 오분류율에 대한 별도 모니터링 기준 없음",
    ],
    "prompt": (
        "위 사실관계만을 이용하여 금융감독원 IT검사 확인서 전체 초안을 작성해 보세요. "
        "사실관계, 직접 원인, 통제 미흡, 고객 영향, 확인·조치사항이 자연스럽게 이어지도록 작성하되, "
        "제시되지 않은 사실은 추가하지 마세요."
    ),
    "sample": (
        "○○은행은 고객 거래내역을 AI로 분석하여 급여이체·카드사용·자동이체 등 우대금리 조건 충족 여부를 판정하고, "
        "그 결과를 우대금리 코드로 생성하여 이자계산 배치시스템에 반영하는 시스템을 2026년 4월부터 운영하였다. "
        "2026년 7월 고객 민원을 계기로 점검한 결과, AI 판정기능이 거래 적요에 ‘급여’ 문구가 포함된 일부 개인 간 송금을 "
        "실제 급여이체로 오분류하였고, 해당 판정결과가 별도의 검증절차 없이 이자계산 배치에 직접 반영된 사실이 확인되었다.\n\n"
        "이로 인해 1,240명의 고객에게 우대금리가 과다 적용되어 총 2,800만원이 과다 지급되었고, 318명의 고객에게는 "
        "우대금리가 적용되지 않아 총 940만원이 과소 지급되었다. 운영 전 테스트는 50명의 고객 사례에 한정되어 있었으며, "
        "개인 간 송금 등 예외·경계사례에 대한 테스트는 실시되지 않았다. 또한 2026년 5월 외부업체가 AI 판정 Prompt를 변경하였으나 "
        "이에 대한 내부 변경요청, 책임자 승인 및 재테스트 기록이 확인되지 않았다.\n\n"
        "아울러 AI 판정결과가 별도 검증 없이 이자계산 배치에 직접 반영되었고, 사후 검증도 고객별 대사가 아닌 전체 이자지급액 합계 확인에 "
        "그쳤으며, 운영 이후 AI 오분류율을 점검하기 위한 별도 모니터링 기준도 마련되어 있지 않았다. 이에 따라 AI 판정결과가 고객별 "
        "우대금리 적용에 반영되는 과정에서 오류를 조기에 탐지·차단할 수 있는 테스트, 변경관리, 검증 및 사후 모니터링 통제가 충분히 작동하지 않은 "
        "것으로 확인되었다."
    ),
}

def login_gate():
    st.session_state.setdefault("authenticated", False)
    if st.session_state.authenticated:
        return

    st.title("💬 금융 AI 참여화면")
    st.caption("오늘 강의에서 사례별 질문과 실시간 의견을 함께 확인합니다.")
    password = str(get_secret("APP_PASSWORD", "sbi2026"))
    entered = st.text_input("접속 비밀번호", type="password")
    if st.button("입장", use_container_width=True):
        if entered == password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")
    st.stop()


def register_nickname():
    if st.session_state.get("nickname"):
        nickname = st.session_state.nickname
        with db_conn() as conn:
            conn.execute(
                "UPDATE participants SET last_seen=? WHERE nickname=?",
                (datetime.now().isoformat(timespec="seconds"), nickname),
            )
            conn.commit()
        return nickname

    st.title("금융권 AI 사례 & 규제대응")
    st.subheader("참여자 닉네임을 입력해 주세요")
    st.caption("실명 대신 오늘 사용할 이름이나 별칭을 입력하셔도 됩니다.")

    nickname = st.text_input("닉네임", max_chars=20, placeholder="예: AI초보, 김IT, 7번")
    if st.button("참여 시작", use_container_width=True):
        clean = " ".join(nickname.strip().split())
        if len(clean) < 2:
            st.warning("닉네임을 2자 이상 입력해 주세요.")
            st.stop()

        with db_conn() as conn:
            existing = conn.execute(
                "SELECT nickname FROM participants WHERE nickname=?", (clean,)
            ).fetchone()
            if existing:
                st.error("이미 사용 중인 닉네임입니다. 다른 닉네임을 입력해 주세요.")
                st.stop()

            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO participants(nickname, joined_at, last_seen) VALUES(?,?,?)",
                (clean, now, now),
            )
            conn.commit()

        st.session_state.nickname = clean
        st.session_state.show_welcome = True
        st.rerun()

    st.stop()



def render_welcome_screen(nickname):
    st.markdown(
        f"""
        <div style="
            padding: 2.2rem 1.5rem;
            text-align: center;
            border-radius: 18px;
            background: #f6f8fb;
            border: 1px solid #e7eaf0;
            margin: 1rem 0 1.5rem 0;
        ">
            <div style="font-size: 1.15rem; color: #6b7280; margin-bottom: .5rem;">
                참여자 입장 완료
            </div>
            <div style="font-size: 3.2rem; font-weight: 800; line-height: 1.15; color: #1f2937;">
                {nickname} 님
            </div>
            <div style="font-size: 1.35rem; margin-top: .8rem; color: #374151;">
                반갑습니다. 오늘 금융 AI 사례에 함께 참여합니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("참여 시작하기", type="primary", use_container_width=True):
        st.session_state.show_welcome = False
        st.rerun()
    st.stop()

def get_state():
    with db_conn() as conn:
        row = conn.execute(
            "SELECT current_case, phase, display_mode, updated_at FROM app_state WHERE id=1"
        ).fetchone()
    return {
        "current_case": int(row[0]),
        "phase": row[1],
        "display_mode": row[2],
        "updated_at": row[3],
    }


def set_state(current_case, phase, display_mode):
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE app_state
            SET current_case=?, phase=?, display_mode=?, updated_at=?
            WHERE id=1
            """,
            (
                current_case,
                phase,
                display_mode,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def save_response(nickname, case_id, phase, answer):
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO responses(nickname, case_id, phase, answer, answered_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(nickname, case_id, phase)
            DO UPDATE SET answer=excluded.answer, answered_at=excluded.answered_at
            """,
            (
                nickname,
                case_id,
                phase,
                answer,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def get_my_response(nickname, case_id, phase):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT answer FROM responses WHERE nickname=? AND case_id=? AND phase=?",
            (nickname, case_id, phase),
        ).fetchone()
    return row[0] if row else None


def get_counts(case_id, phase):
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT answer, COUNT(*)
            FROM responses
            WHERE case_id=? AND phase=?
            GROUP BY answer
            """,
            (case_id, phase),
        ).fetchall()
    return {answer: count for answer, count in rows}



def get_exercise_state():
    with db_conn() as conn:
        row = conn.execute(
            "SELECT current_exercise, display_mode, spotlight_nickname, updated_at FROM exercise_state WHERE id=1"
        ).fetchone()
    return {
        "current_exercise": int(row[0]),
        "display_mode": row[1],
        "spotlight_nickname": row[2],
        "updated_at": row[3],
    }


def set_exercise_state(current_exercise, display_mode, spotlight_nickname=""):
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE exercise_state
            SET current_exercise=?, display_mode=?, spotlight_nickname=?, updated_at=?
            WHERE id=1
            """,
            (
                current_exercise,
                display_mode,
                spotlight_nickname,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def save_exercise_response(nickname, exercise_id, judgment, reason, procedure):
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO exercise_responses
            (nickname, exercise_id, judgment, reason, procedure, answered_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(nickname, exercise_id)
            DO UPDATE SET
                judgment=excluded.judgment,
                reason=excluded.reason,
                procedure=excluded.procedure,
                answered_at=excluded.answered_at
            """,
            (
                nickname,
                exercise_id,
                judgment,
                reason,
                procedure,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def get_exercise_response(nickname, exercise_id):
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT judgment, reason, procedure, answered_at
            FROM exercise_responses
            WHERE nickname=? AND exercise_id=?
            """,
            (nickname, exercise_id),
        ).fetchone()
    return row


def exercise_response_count(exercise_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM exercise_responses WHERE exercise_id=?",
            (exercise_id,),
        ).fetchone()[0]


def get_exercise_responses(exercise_id):
    with db_conn() as conn:
        return conn.execute(
            """
            SELECT nickname, judgment, reason, procedure, answered_at
            FROM exercise_responses
            WHERE exercise_id=?
            ORDER BY answered_at
            """,
            (exercise_id,),
        ).fetchall()



def get_confirmation_state():
    with db_conn() as conn:
        row = conn.execute(
            "SELECT display_mode, spotlight_nickname, updated_at "
            "FROM confirmation_state WHERE id=1"
        ).fetchone()
    return {
        "display_mode": row[0],
        "spotlight_nickname": row[1],
        "updated_at": row[2],
    }


def set_confirmation_state(display_mode, spotlight_nickname=""):
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE confirmation_state
            SET display_mode=?, spotlight_nickname=?, updated_at=?
            WHERE id=1
            """,
            (
                display_mode,
                spotlight_nickname,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def save_confirmation_response(nickname, answer):
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO confirmation_responses(nickname, answer, answered_at)
            VALUES(?,?,?)
            ON CONFLICT(nickname)
            DO UPDATE SET answer=excluded.answer, answered_at=excluded.answered_at
            """,
            (nickname, answer, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


def get_confirmation_response(nickname):
    with db_conn() as conn:
        return conn.execute(
            "SELECT answer, answered_at FROM confirmation_responses WHERE nickname=?",
            (nickname,),
        ).fetchone()


def confirmation_response_count():
    with db_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM confirmation_responses"
        ).fetchone()[0]


def get_confirmation_responses():
    with db_conn() as conn:
        return conn.execute(
            """
            SELECT nickname, answer, answered_at
            FROM confirmation_responses
            ORDER BY answered_at
            """
        ).fetchall()



def confirmation_answer_hash(answer):
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def get_confirmation_ai_review(nickname, answer):
    answer_hash = confirmation_answer_hash(answer)
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT review_text, reviewed_at
            FROM confirmation_ai_reviews
            WHERE nickname=? AND answer_hash=?
            """,
            (nickname, answer_hash),
        ).fetchone()
    return row


def save_confirmation_ai_review(nickname, answer, review_text):
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO confirmation_ai_reviews
            (nickname, answer_hash, review_text, reviewed_at)
            VALUES(?,?,?,?)
            ON CONFLICT(nickname)
            DO UPDATE SET
                answer_hash=excluded.answer_hash,
                review_text=excluded.review_text,
                reviewed_at=excluded.reviewed_at
            """,
            (
                nickname,
                confirmation_answer_hash(answer),
                review_text,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def build_confirmation_review_prompt(answer):
    facts = "\\n".join([f"- {x}" for x in CONFIRMATION_LAB["facts"]])
    return f"""
당신은 금융회사 IT검사 확인서 작성 교육의 검토자입니다.
아래 수강생 답안을 '제공된 사실관계만' 기준으로 검토하세요.

[절대 원칙]
- 제공되지 않은 사실을 새로 만들지 마세요.
- 법규 위반 여부를 단정하지 마세요.
- 추정이나 책임회피 표현을 사실처럼 쓰지 마세요.
- 답안의 문장력보다 사실관계, 직접 원인, 통제 미흡, 고객 영향, 조치사항의 연결성을 우선 평가하세요.
- 수정안에도 제공된 사실관계 외 내용을 추가하지 마세요.

[사례]
{CONFIRMATION_LAB["scenario"]}

[고객 영향]
{CONFIRMATION_LAB["impact"]}

[확인된 추가 사실]
{facts}

[수강생 답안]
{answer}

아래 형식으로 한국어로 답하세요.

### 종합평가
2~3문장으로 평가

### 항목별 점검
- 사실관계 정확성: 적정 / 보완 필요
- 직접 원인 명확성: 적정 / 보완 필요
- 통제 미흡 구체성: 적정 / 보완 필요
- 고객 영향 반영: 적정 / 보완 필요
- 조치사항 표현: 적정 / 보완 필요
- 근거 없는 내용: 없음 / 있음
- 책임회피·모호 표현: 없음 / 있음

### 보완할 부분
최대 5개. 각 항목은 '문제 → 왜 문제인지 → 어떻게 고칠지' 순서로 작성

### 수정 예시
수강생 답안의 장점을 최대한 유지하면서 확인서 전체 초안을 다시 작성.
제공된 사실관계만 사용.
""".strip()


def run_confirmation_ai_review(answer):
    api_key = get_secret("OPENAI_API_KEY", None)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 Streamlit Secrets에 설정되어 있지 않습니다.")

    model = str(get_secret("MODEL", "gpt-5-mini"))
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=build_confirmation_review_prompt(answer),
    )
    text = getattr(response, "output_text", None)
    if not text:
        raise RuntimeError("AI 검토 결과를 받지 못했습니다.")
    return text.strip()


def participant_count():
    with db_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]


def render_results(case_id, phase):
    case = CASES[case_id]
    counts = get_counts(case_id, phase)
    total = sum(counts.get(option, 0) for option in case["options"])

    st.markdown(f"### 전체 응답 결과 · {total}명")

    # 좁은 노트북 화면에서도 잘리지 않도록 Streamlit 기본 차트 대신
    # 간결한 진행바 형태로 결과를 표시한다.
    for option in case["options"]:
        count = counts.get(option, 0)
        pct = (count / total * 100) if total else 0

        left, right = st.columns([5, 1])
        with left:
            st.markdown(f"**{option}**")
            st.progress(pct / 100 if total else 0)
        with right:
            st.markdown(
                f"<div style='text-align:right;padding-top:.15rem;'>"
                f"<b>{count}명</b><br>"
                f"<span style='color:#64748b;font-size:.9rem;'>{pct:.0f}%</span>"
                f"</div>",
                unsafe_allow_html=True,
            )


@st.fragment(run_every=2)
def participant_live_area(nickname):
    state = get_state()
    mode = state["display_mode"]

    if state["current_case"] == 0 or mode == "waiting":
        st.markdown("## 다음 질문을 기다려 주세요")
        st.caption("진행자가 다음 사례를 시작하면 이 화면이 자동으로 바뀝니다.")
        return

    case_id = state["current_case"]
    phase = state["phase"]
    case = CASES[case_id]
    phase_label = "사전 질문" if phase == "pre" else "사후 질문"

    st.markdown(f"## {case['title']}")
    st.caption(phase_label)

    if mode == "question":
        st.info("사례 설명을 듣기 전에, 지금 생각을 먼저 선택해 주세요.")
        st.markdown(f"### {case['question']}")
        st.caption(f"생각할 포인트: {case['focus']}")

        existing = get_my_response(nickname, case_id, phase)
        default_index = case["options"].index(existing) if existing in case["options"] else None

        choice = st.radio(
            "하나를 선택해 주세요.",
            case["options"],
            index=default_index,
            key=f"vote_{case_id}_{phase}",
        )

        if st.button(
            "응답 제출",
            use_container_width=True,
            type="primary",
            disabled=choice is None,
            key=f"submit_{case_id}_{phase}",
        ):
            save_response(nickname, case_id, phase, choice)
            st.success("응답이 제출되었습니다. 잠시 후 전체 결과가 공개됩니다.")

        my_answer = get_my_response(nickname, case_id, phase)
        if my_answer:
            st.success(f"내 응답: {my_answer}")
            st.caption("진행자가 결과를 공개하면 이 화면이 자동으로 전환됩니다.")

    elif mode == "results":
        my_answer = get_my_response(nickname, case_id, phase)
        st.success("📊 전체 결과가 공개되었습니다.")
        if my_answer:
            st.caption(f"내 응답: {my_answer}")
        render_results(case_id, phase)
        st.info(f"생각할 포인트: {case['focus']}")



@st.fragment(run_every=2)
def participant_exercise_area(nickname):
    ex_state = get_exercise_state()
    ex_id = ex_state["current_exercise"]
    mode = ex_state["display_mode"]

    if ex_id == 0 or mode == "waiting":
        return False

    ex = EXERCISES[ex_id]

    if mode == "exercise":
        st.markdown(f"## ✍️ {ex['title']}")
        st.markdown(f"### {ex['question']}")
        st.info(f"답안 작성 포인트: {ex['points']}")
        st.caption(f"힌트: {ex['hint']}")

        existing = get_exercise_response(nickname, ex_id)
        prior_judgment = existing[0] if existing else None
        prior_reason = existing[1] if existing else ""
        prior_procedure = existing[2] if existing else ""

        options = ["가능", "불가", "조건부"]
        idx = options.index(prior_judgment) if prior_judgment in options else None

        judgment = st.radio(
            "① 판단",
            options,
            index=idx,
            horizontal=True,
            key=f"ex_judgment_{ex_id}",
        )
        reason = st.text_area(
            "② 근거 — 고객영향·법규·운영위험",
            value=prior_reason,
            height=150,
            placeholder="왜 그렇게 판단했는지 3~5줄 정도로 적어보세요.",
            key=f"ex_reason_{ex_id}",
        )
        procedure = st.text_area(
            "③ 필요한 절차 — 중단·확인·승인·기록",
            value=prior_procedure,
            height=150,
            placeholder="실제 업무라면 어떤 절차가 필요할지 적어보세요.",
            key=f"ex_procedure_{ex_id}",
        )

        if st.button(
            "답안 제출",
            type="primary",
            use_container_width=True,
            disabled=(judgment is None or not reason.strip() or not procedure.strip()),
            key=f"ex_submit_{ex_id}",
        ):
            save_exercise_response(
                nickname, ex_id, judgment, reason.strip(), procedure.strip()
            )
            st.success("답안이 제출되었습니다.")

        if get_exercise_response(nickname, ex_id):
            st.success(
                f"제출 완료 · 현재 {exercise_response_count(ex_id)}/{participant_count()}명 제출"
            )
        else:
            st.caption(
                f"현재 {exercise_response_count(ex_id)}/{participant_count()}명 제출"
            )
        return True

    if mode == "review":
        st.markdown(f"## 💬 {ex['title']} · 답안 같이 보기")
        st.markdown(f"### {ex['question']}")
        st.caption(
            f"현재 {exercise_response_count(ex_id)}/{participant_count()}명 제출"
        )

        spotlight = ex_state["spotlight_nickname"]
        if spotlight:
            row = get_exercise_response(spotlight, ex_id)
            if row:
                judgment, reason, procedure, _ = row
                st.markdown("### 강사가 선택한 답안")
                st.markdown(
                    f"""
                    <div style="padding:1.4rem 1.5rem;border:1px solid #e5e7eb;
                         border-radius:16px;background:#f8fafc;">
                      <div style="font-size:1.6rem;font-weight:800;margin-bottom:.7rem;">
                        {spotlight}
                      </div>
                      <div style="margin-bottom:.8rem;"><b>① 판단</b> · {judgment}</div>
                      <div style="margin-bottom:.8rem;"><b>② 근거</b><br>{reason}</div>
                      <div><b>③ 필요한 절차</b><br>{procedure}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("진행자가 함께 볼 답안을 선택하고 있습니다.")

        my_row = get_exercise_response(nickname, ex_id)
        if my_row:
            with st.expander("내가 제출한 답안 보기"):
                st.write("① 판단:", my_row[0])
                st.write("② 근거:", my_row[1])
                st.write("③ 필요한 절차:", my_row[2])
        return True

    return False



@st.fragment(run_every=2)
def shared_join_banner():
    """
    모든 참여자 화면에서 최근 입장자를 함께 보여준다.
    최근 15초 안에 들어온 최대 3명을 표시하며 이후 자동으로 사라진다.
    """
    now = datetime.now()
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT nickname, joined_at
            FROM participants
            ORDER BY joined_at DESC
            LIMIT 5
            """
        ).fetchall()

    recent_names = []
    for nickname, joined_at in rows:
        try:
            joined = datetime.fromisoformat(joined_at)
            age = (now - joined).total_seconds()
            if 0 <= age <= 15:
                recent_names.append(nickname)
        except Exception:
            continue

    recent_names = recent_names[:3]
    if not recent_names:
        return

    if len(recent_names) == 1:
        message = f"{recent_names[0]} 님이 참석했습니다"
    else:
        message = " · ".join(recent_names) + " 님이 참석했습니다"

    st.markdown(
        f"""
        <div style="
            padding: 1.4rem 1.2rem;
            margin: .2rem 0 1.2rem 0;
            text-align: center;
            border-radius: 18px;
            border: 1px solid #dbe5f0;
            background: #f5f8fc;
        ">
            <div style="font-size: 1rem; color:#64748b; margin-bottom:.35rem;">
                👋 방금 입장
            </div>
            <div style="font-size: 2.35rem; line-height:1.25; font-weight:800; color:#1f2937;">
                {message}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )




@st.fragment(run_every=3)
def participant_roster_panel():
    names = all_participants()
    st.markdown(f"### 👥 함께 참여 중 · {len(names)}명")
    if not names:
        st.caption("아직 참여자가 없습니다.")
        return

    # PC 강의용 우측 패널: 닉네임을 2열 태그 형태로 표시
    rows = []
    for i in range(0, len(names), 2):
        left = names[i]
        right = names[i + 1] if i + 1 < len(names) else ""
        rows.append((left, right))

    for left_name, right_name in rows:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f"<div style='padding:.48rem .55rem;margin:.12rem 0;"
                f"border:1px solid #dbe3ec;border-radius:10px;"
                f"background:#f8fafc;font-weight:650;text-align:center;'>"
                f"{left_name}</div>",
                unsafe_allow_html=True,
            )
        with c2:
            if right_name:
                st.markdown(
                    f"<div style='padding:.48rem .55rem;margin:.12rem 0;"
                    f"border:1px solid #dbe3ec;border-radius:10px;"
                    f"background:#f8fafc;font-weight:650;text-align:center;'>"
                    f"{right_name}</div>",
                    unsafe_allow_html=True,
                )




def participant_confirmation_area(nickname):
    state = get_confirmation_state()
    mode = state["display_mode"]

    if mode == "waiting":
        return False

    st.markdown(f"## 📝 {CONFIRMATION_LAB['title']}")
    st.markdown("### 상황")
    st.write(CONFIRMATION_LAB["scenario"])
    st.warning(CONFIRMATION_LAB["impact"])

    with st.expander("확인된 추가 사실 보기", expanded=True):
        for fact in CONFIRMATION_LAB["facts"]:
            st.markdown(f"- {fact}")

    if mode == "write":
        st.info(CONFIRMATION_LAB["prompt"])
        st.markdown(
            """
            **작성 가이드**
            1. 사실관계 및 시스템 처리구조
            2. 오류 발생 내용과 직접 원인
            3. 테스트·변경관리·검증·모니터링 등 통제 미흡
            4. 고객 영향
            5. 확인 이후 중단·재산정·보완 등 조치사항
            """
        )
        existing = get_confirmation_response(nickname)
        prior = existing[0] if existing else ""
        answer = st.text_area(
            "확인서 전체 초안",
            value=prior,
            height=420,
            placeholder="사실관계 → 직접 원인 → 통제 미흡 → 고객 영향 → 확인·조치사항의 흐름으로 전체 확인서를 작성해 보세요.",
            key="confirmation_answer",
        )
        if st.button(
            "확인서 답안 제출",
            type="primary",
            use_container_width=True,
            disabled=not answer.strip(),
            key="confirmation_submit",
        ):
            save_confirmation_response(nickname, answer.strip())
            st.success("답안이 제출되었습니다.")

        saved = get_confirmation_response(nickname)
        if saved:
            st.success(
                f"제출 완료 · 현재 {confirmation_response_count()}/{participant_count()}명 제출"
            )

            st.divider()
            st.markdown("### 🤖 AI 검토")
            st.caption(
                "제출한 확인서를 사실관계·직접 원인·통제 미흡·고객 영향·조치사항 기준으로 점검합니다."
            )

            existing_review = get_confirmation_ai_review(nickname, saved[0])

            if st.button(
                "AI 검토 받기" if not existing_review else "AI 다시 검토하기",
                use_container_width=True,
                key="confirmation_ai_review_btn",
            ):
                with st.spinner("확인서를 검토하고 있습니다..."):
                    try:
                        review = run_confirmation_ai_review(saved[0])
                        save_confirmation_ai_review(nickname, saved[0], review)
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI 검토 중 오류가 발생했습니다: {e}")

            review_row = get_confirmation_ai_review(nickname, saved[0])
            if review_row:
                st.markdown(review_row[0])
                st.caption("※ 교육용 AI 검토 결과입니다. 최종 판단은 강의 해설과 함께 확인하세요.")
        else:
            st.caption(
                f"현재 {confirmation_response_count()}/{participant_count()}명 제출"
            )
        return True

    if mode in ("review", "sample"):
        st.markdown("### 함께 볼 답안")
        spotlight = state["spotlight_nickname"]
        if spotlight:
            row = get_confirmation_response(spotlight)
            if row:
                st.markdown(
                    f"""
                    <div style="padding:1.4rem 1.5rem;border:1px solid #e5e7eb;
                         border-radius:16px;background:#f8fafc;">
                      <div style="font-size:1.6rem;font-weight:800;margin-bottom:.7rem;">
                        {spotlight}
                      </div>
                      <div style="font-size:1.08rem;line-height:1.75;">{row[0]}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                review_row = get_confirmation_ai_review(spotlight, row[0])
                if review_row:
                    st.markdown("### 🤖 AI 검토")
                    st.markdown(review_row[0])
                    st.caption("※ 교육용 AI 검토 결과입니다. 최종 판단은 강의 해설과 함께 확인하세요.")
                else:
                    st.info("이 답안은 아직 AI 검토가 생성되지 않았습니다.")
        else:
            st.info("진행자가 함께 볼 답안을 선택하고 있습니다.")

        if mode == "sample":
            st.markdown("### 강사 예시문")
            st.success(CONFIRMATION_LAB["sample"])

        mine = get_confirmation_response(nickname)
        if mine:
            with st.expander("내가 제출한 답안 보기"):
                st.write(mine[0])
        return True

    return False



@st.fragment(run_every=2)
def participant_activity_router(nickname):
    """
    2초마다 관리자 상태를 다시 확인하여
    대기 → 사례 질문/결과 → 3교시 실습/답안공개 화면으로 자동 전환한다.
    """
    confirm_state = get_confirmation_state()
    ex_state = get_exercise_state()
    case_state = get_state()

    confirmation_active = confirm_state["display_mode"] != "waiting"
    exercise_active = (
        ex_state["current_exercise"] != 0
        and ex_state["display_mode"] != "waiting"
    )
    case_active = (
        case_state["current_case"] != 0
        and case_state["display_mode"] != "waiting"
    )

    if confirmation_active:
        participant_confirmation_area(nickname)
        return

    if exercise_active:
        participant_exercise_area(nickname)
        return

    if case_active:
        participant_live_area(nickname)
        return

    # 관리자 화면이 대기 상태일 때
    st.markdown("## 다음 질문을 기다려 주세요")
    st.caption("진행자가 다음 사례 또는 실습을 시작하면 이 화면이 자동으로 바뀝니다.")


def participant_view():
    login_gate()
    nickname = register_nickname()

    if st.session_state.get("show_welcome", False):
        render_welcome_screen(nickname)

    st.title("금융 AI 사례 · 실시간 참여")
    st.caption(f"참여자: **{nickname}** · 전체 접속: **{participant_count()}명**")

    # PC 강의용 고정 2열 구성
    # 왼쪽: 현재 질문/결과/실습, 오른쪽: 전체 참석자 닉네임
    main_col, roster_col = st.columns([4.2, 1.15], gap="large")

    with main_col:
        shared_join_banner()
        participant_activity_router(nickname)

    with roster_col:
        participant_roster_panel()


def admin_auth():
    login_gate()
    st.session_state.setdefault("admin_authenticated", False)
    if st.session_state.admin_authenticated:
        return

    st.title("진행 관리")
    app_pw = str(get_secret("APP_PASSWORD", "sbi2026"))
    admin_pw = str(get_secret("ADMIN_PASSWORD", app_pw))
    entered = st.text_input("관리 비밀번호", type="password")
    if st.button("관리 화면 열기", use_container_width=True):
        if entered == admin_pw:
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")
    st.stop()




def all_participants():
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT nickname
            FROM participants
            ORDER BY joined_at ASC
            """
        ).fetchall()
    return [r[0] for r in rows]


@st.fragment(run_every=3)
def participant_roster():
    names = all_participants()
    if not names:
        return

    st.markdown("### 👥 함께 참여 중")

    # 여러 줄로 들여쓴 HTML은 Markdown 코드블록으로 해석될 수 있으므로
    # 한 줄 HTML로 만들어 렌더링한다.
    chips = "".join(
        [
            '<span style="display:inline-block;'
            'padding:.42rem .72rem;'
            'margin:.2rem .22rem .2rem 0;'
            'border-radius:999px;'
            'background:#f1f5f9;'
            'border:1px solid #dbe3ec;'
            'font-size:.98rem;'
            'font-weight:650;'
            'color:#334155;">'
            + str(name) +
            '</span>'
            for name in names
        ]
    )

    roster_html = '<div style="margin:.2rem 0 .7rem 0;">' + chips + '</div>'
    st.markdown(roster_html, unsafe_allow_html=True)
    st.caption(f"현재 {len(names)}명 참여 중")



def recent_participants(limit=5):
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT nickname, joined_at
            FROM participants
            ORDER BY joined_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows

def responses_df():
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT nickname, case_id, phase, answer, answered_at
            FROM responses
            ORDER BY answered_at
            """
        ).fetchall()
    return pd.DataFrame(
        rows,
        columns=["nickname", "case_id", "phase", "answer", "answered_at"],
    )



def render_exercise_admin():
    ex_state = get_exercise_state()

    st.markdown("## ✍️ 3교시 · 상황별 실습 Q1~Q6")
    st.caption(
        "실습을 하나씩 열고, 제출현황을 확인한 뒤 특정 답안을 전체 화면에 띄울 수 있습니다."
    )

    ex_options = list(EXERCISES.keys())
    default_ex = ex_state["current_exercise"] if ex_state["current_exercise"] in ex_options else 1
    ex_id = st.selectbox(
        "실습 선택",
        ex_options,
        index=ex_options.index(default_ex),
        format_func=lambda x: f"Q{x} · {EXERCISES[x]['question']}",
        key="admin_exercise_select",
    )
    ex = EXERCISES[ex_id]

    st.info(ex["question"])
    st.caption(f"답안 작성 포인트: {ex['points']}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("▶ 실습 시작", type="primary", use_container_width=True):
            set_state(0, "pre", "waiting")
            set_exercise_state(ex_id, "exercise", "")
            st.success(f"Q{ex_id} 입력화면을 열었습니다.")
            st.rerun()
    with c2:
        if st.button("💬 작성 종료 · 답안 보기", use_container_width=True, key="confirm_close_btn"):
            set_exercise_state(ex_id, "review", "")
            st.success(f"Q{ex_id} 제출을 종료했습니다.")
            st.rerun()
    with c3:
        if st.button("⏸ 실습 대기", use_container_width=True):
            set_exercise_state(0, "waiting", "")
            st.success("실습 화면을 대기로 전환했습니다.")
            st.rerun()

    total = participant_count()
    count = exercise_response_count(ex_id)
    st.metric("현재 제출", f"{count}/{total}명")

    rows = get_exercise_responses(ex_id)
    if not rows:
        st.caption("아직 제출된 답안이 없습니다.")
        return

    df = pd.DataFrame(
        rows,
        columns=["닉네임", "판단", "근거", "필요한 절차", "제출시각"],
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("### 전체 화면에 띄울 답안")
    names = [r[0] for r in rows]
    current = ex_state["spotlight_nickname"]
    idx = names.index(current) if current in names else 0
    selected = st.selectbox(
        "답안 선택",
        names,
        index=idx,
        key=f"spotlight_select_{ex_id}",
    )

    s1, s2 = st.columns(2)
    with s1:
        if st.button("📺 선택 답안 전체 공개", use_container_width=True):
            set_exercise_state(ex_id, "review", selected)
            st.success(f"{selected}님의 답안을 참여자 화면에 공개했습니다.")
            st.rerun()
    with s2:
        if st.button("공개 답안 숨기기", use_container_width=True):
            set_exercise_state(ex_id, "review", "")
            st.success("공개 답안을 숨겼습니다.")
            st.rerun()



def render_confirmation_admin():
    state = get_confirmation_state()

    st.markdown("## 📝 마지막 실습 · FSS IT검사 확인서 작성")
    st.caption(
        "수강생이 확인서 전체 초안을 작성하고, 강사가 특정 답안을 닉네임과 함께 전체 화면에 공개합니다."
    )

    st.info(CONFIRMATION_LAB["prompt"])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("▶ 확인서 작성 시작", type="primary", use_container_width=True, key="confirm_start_btn"):
            set_state(0, "pre", "waiting")
            set_exercise_state(0, "waiting", "")
            set_confirmation_state("write", "")
            st.success("확인서 작성 화면을 열었습니다.")
            st.rerun()
    with c2:
        if st.button("💬 제출 종료 · 답안 보기", use_container_width=True):
            set_confirmation_state("review", "")
            st.success("제출을 종료했습니다.")
            st.rerun()
    with c3:
        if st.button("📘 강사 작성예시 공개", use_container_width=True, key="confirm_sample_btn"):
            current = get_confirmation_state()["spotlight_nickname"]
            set_confirmation_state("sample", current)
            st.success("강사 예시문을 공개했습니다.")
            st.rerun()
    with c4:
        if st.button("⏸ 확인서 작성 대기", use_container_width=True, key="confirm_wait_btn"):
            set_confirmation_state("waiting", "")
            st.success("확인서 실습을 대기 상태로 전환했습니다.")
            st.rerun()

    count = confirmation_response_count()
    st.metric("현재 제출", f"{count}/{participant_count()}명")

    rows = get_confirmation_responses()
    if not rows:
        st.caption("아직 제출된 답안이 없습니다.")
        return

    df = pd.DataFrame(rows, columns=["닉네임", "확인서 전체 초안", "제출시각"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    names = [r[0] for r in rows]
    current = state["spotlight_nickname"]
    idx = names.index(current) if current in names else 0
    selected = st.selectbox(
        "전체 화면에 띄울 답안",
        names,
        index=idx,
        key="confirmation_spotlight_select",
    )

    selected_row = get_confirmation_response(selected)

    a1, a2, a3 = st.columns(3)
    with a1:
        if st.button("🤖 AI 검토 생성", use_container_width=True, key="confirmation_admin_ai_review_btn"):
            if selected_row:
                with st.spinner(f"{selected}님의 확인서를 AI가 검토하고 있습니다..."):
                    try:
                        review = run_confirmation_ai_review(selected_row[0])
                        save_confirmation_ai_review(selected, selected_row[0], review)
                        st.success("AI 검토를 생성했습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI 검토 중 오류가 발생했습니다: {e}")

    with a2:
        if st.button("📺 답안+AI검토 전체 공개", use_container_width=True, key="confirmation_publish_btn"):
            set_confirmation_state("review", selected)
            st.success(f"{selected}님의 답안과 AI 검토를 전체 공개했습니다.")
            st.rerun()

    with a3:
        if st.button("공개 답안 숨기기", use_container_width=True, key="confirmation_hide_btn"):
            set_confirmation_state("review", "")
            st.success("공개 답안을 숨겼습니다.")
            st.rerun()

    if selected_row:
        review_row = get_confirmation_ai_review(selected, selected_row[0])
        if review_row:
            with st.expander(f"🤖 {selected}님의 AI 검토 결과", expanded=True):
                st.markdown(review_row[0])
        else:
            st.caption("아직 AI 검토가 없습니다. 먼저 'AI 검토 생성'을 눌러 주세요.")


def admin_view():
    admin_auth()
    state = get_state()

    st.title("📊 금융 AI 참여 · 진행 관리")
    st.caption("사례를 선택한 뒤 아래 3개 버튼으로 참여자 화면을 제어합니다.")

    m1, m2, m3 = st.columns(3)
    m1.metric("등록 참여자", f"{participant_count()}명")
    m2.metric(
        "현재 사례",
        "대기" if state["current_case"] == 0 else f"사례 {state['current_case']}",
    )
    mode_label = {
        "waiting": "대기",
        "question": "질문 응답 중",
        "results": "결과 공개",
    }.get(state["display_mode"], state["display_mode"])
    m3.metric("참여자 화면", mode_label)

    recent = recent_participants(5)
    if recent:
        latest_name = recent[0][0]
        st.markdown("### 👋 방금 입장")
        st.markdown(
            f"""
            <div style="
                padding: 1.35rem 1.5rem;
                border-radius: 16px;
                background: #f6f8fb;
                border: 1px solid #e7eaf0;
                margin-bottom: .7rem;
            ">
                <div style="font-size: 2.4rem; font-weight: 800; color: #1f2937;">
                    {latest_name}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        names = " · ".join([r[0] for r in recent])
        st.caption(f"최근 입장: {names}")

    st.divider()
    st.markdown("## 1·2교시 · 사례 사전질문")
    st.markdown("### 1. 질문 선택")

    case_options = list(CASES.keys())
    default_case = state["current_case"] if state["current_case"] in case_options else 1

    current_case = st.selectbox(
        "사례 선택",
        case_options,
        index=case_options.index(default_case),
        format_func=lambda x: CASES[x]["title"],
    )

    phase = st.radio(
        "질문 구분",
        ["pre", "post"],
        index=0 if state["phase"] == "pre" else 1,
        format_func=lambda x: "사전 질문" if x == "pre" else "사후 질문",
        horizontal=True,
    )

    st.markdown("### 2. 참여자 화면 제어")
    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("▶ 질문 열기", type="primary", use_container_width=True):
            set_state(current_case, phase, "question")
            st.success("참여자 화면에 질문을 열었습니다.")
            st.rerun()

    with c2:
        if st.button("📊 투표 종료 · 결과 공개", use_container_width=True):
            set_state(current_case, phase, "results")
            st.success("참여자 화면에 전체 결과를 공개했습니다.")
            st.rerun()

    with c3:
        if st.button("⏸ 대기 화면으로", use_container_width=True):
            set_state(0, "pre", "waiting")
            st.success("참여자 화면을 대기 상태로 전환했습니다.")
            st.rerun()

    st.caption(
        "참여자 화면은 약 2초마다 자동 갱신됩니다. "
        "교육생이 새로고침 버튼을 누를 필요가 없습니다."
    )

    st.divider()
    st.markdown("### 3. 현재 응답 현황")

    # 현재 관리자가 선택한 사례/단계 기준으로 항상 집계 표시
    render_results(current_case, phase)

    with db_conn() as conn:
        answered = conn.execute(
            """
            SELECT nickname, answer, answered_at
            FROM responses
            WHERE case_id=? AND phase=?
            ORDER BY answered_at
            """,
            (current_case, phase),
        ).fetchall()

    if answered:
        st.dataframe(
            pd.DataFrame(answered, columns=["닉네임", "응답", "응답시각"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("아직 제출된 응답이 없습니다.")


    st.divider()
    render_exercise_admin()

    st.divider()
    render_confirmation_admin()

    st.divider()
    st.markdown("### 전체 응답 관리")
    df = responses_df()

    d1, d2 = st.columns(2)
    with d1:
        if not df.empty:
            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "사례투표 CSV 다운로드",
                data=csv_bytes,
                file_name="financial_ai_votes.csv",
                mime="text/csv",
                use_container_width=True,
            )

    with db_conn() as conn:
        ex_rows = conn.execute(
            """
            SELECT nickname, exercise_id, judgment, reason, procedure, answered_at
            FROM exercise_responses
            ORDER BY exercise_id, answered_at
            """
        ).fetchall()
    ex_df = pd.DataFrame(
        ex_rows,
        columns=["nickname", "exercise_id", "judgment", "reason", "procedure", "answered_at"],
    )
    with d2:
        if not ex_df.empty:
            ex_csv = ex_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "상황별 실습 CSV 다운로드",
                data=ex_csv,
                file_name="financial_ai_exercises.csv",
                mime="text/csv",
                use_container_width=True,
            )

    confirm_rows = get_confirmation_responses()
    if confirm_rows:
        confirm_df = pd.DataFrame(
            confirm_rows,
            columns=["nickname", "answer", "answered_at"],
        )
        confirm_csv = confirm_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "확인서 실습 CSV 다운로드",
            data=confirm_csv,
            file_name="financial_ai_confirmation_lab.csv",
            mime="text/csv",
            use_container_width=True,
        )

    r1, r2 = st.columns(2)
    with r1:
        if st.button("응답만 초기화", use_container_width=True):
            with db_conn() as conn:
                conn.execute("DELETE FROM responses")
                conn.execute("DELETE FROM exercise_responses")
                conn.execute("DELETE FROM confirmation_responses")
                conn.execute("DELETE FROM confirmation_ai_reviews")
                conn.execute(
                    """
                    UPDATE confirmation_state
                    SET display_mode='waiting', spotlight_nickname='', updated_at=?
                    WHERE id=1
                    """,
                    (datetime.now().isoformat(timespec="seconds"),),
                )
                conn.execute(
                    """
                    UPDATE exercise_state
                    SET current_exercise=0, display_mode='waiting',
                        spotlight_nickname='', updated_at=?
                    WHERE id=1
                    """,
                    (datetime.now().isoformat(timespec="seconds"),),
                )
                conn.commit()
            st.success("모든 응답을 초기화했습니다.")
            st.rerun()

    with r2:
        confirm = st.checkbox("참여자 명단까지 초기화합니다", key="reset_people_confirm")
        if st.button("전체 초기화", use_container_width=True, disabled=not confirm):
            with db_conn() as conn:
                conn.execute("DELETE FROM responses")
                conn.execute("DELETE FROM exercise_responses")
                conn.execute("DELETE FROM confirmation_responses")
                conn.execute("DELETE FROM confirmation_ai_reviews")
                conn.execute("DELETE FROM participants")
                conn.execute(
                    """
                    UPDATE confirmation_state
                    SET display_mode='waiting', spotlight_nickname='', updated_at=?
                    WHERE id=1
                    """,
                    (datetime.now().isoformat(timespec="seconds"),),
                )
                conn.execute(
                    """
                    UPDATE app_state
                    SET current_case=0, phase='pre', display_mode='waiting', updated_at=?
                    WHERE id=1
                    """,
                    (datetime.now().isoformat(timespec="seconds"),),
                )
                conn.execute(
                    """
                    UPDATE exercise_state
                    SET current_exercise=0, display_mode='waiting',
                        spotlight_nickname='', updated_at=?
                    WHERE id=1
                    """,
                    (datetime.now().isoformat(timespec="seconds"),),
                )
                conn.commit()
            st.success("참여자와 응답을 모두 초기화했습니다.")
            st.rerun()

    st.caption(
        "※ 수업 1회용 경량 구조입니다. Streamlit 앱 재시작 시 /tmp의 응답 데이터가 초기화될 수 있으므로 "
        "필요한 결과는 CSV로 내려받아 보관하세요."
    )


def main():
    init_db()
    view = st.query_params.get("view", "participant")

    if view == "admin":
        admin_view()
    else:
        participant_view()


if __name__ == "__main__":
    main()
