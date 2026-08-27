
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("/tmp/financial_ai_participation.db")

st.set_page_config(
    page_title="금융 AI 참여화면",
    page_icon="💬",
    layout="wide",
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
        cols = [r[1] for r in conn.execute("PRAGMA table_info(app_state)").fetchall()]
        if "display_mode" not in cols:
            conn.execute(
                "ALTER TABLE app_state ADD COLUMN display_mode TEXT NOT NULL DEFAULT 'waiting'"
            )
        if "current_case" not in cols:
            conn.execute(
                "ALTER TABLE app_state ADD COLUMN current_case INTEGER NOT NULL DEFAULT 0"
            )
        if "phase" not in cols:
            conn.execute(
                "ALTER TABLE app_state ADD COLUMN phase TEXT NOT NULL DEFAULT 'pre'"
            )
        if "updated_at" not in cols:
            conn.execute(
                "ALTER TABLE app_state ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
            )

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


def participant_count():
    with db_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]


def render_results(case_id, phase):
    case = CASES[case_id]
    counts = get_counts(case_id, phase)
    data = [{"응답": option, "인원": counts.get(option, 0)} for option in case["options"]]
    df = pd.DataFrame(data).set_index("응답")
    total = int(df["인원"].sum())

    st.markdown(f"### 전체 응답 결과 · {total}명")
    st.bar_chart(df, horizontal=True, use_container_width=True)

    cols = st.columns(4)
    for idx, option in enumerate(case["options"]):
        count = counts.get(option, 0)
        pct = (count / total * 100) if total else 0
        cols[idx].metric(option, f"{count}명", f"{pct:.0f}%")


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


def participant_view():
    login_gate()
    nickname = register_nickname()

    st.title("금융 AI 사례 · 실시간 참여")
    st.caption(f"참여자: **{nickname}**  |  전체 접속: **{participant_count()}명**")
    st.divider()

    participant_live_area(nickname)


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

    st.divider()
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
    st.markdown("### 전체 응답 관리")
    df = responses_df()

    if not df.empty:
        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "전체 응답 CSV 다운로드",
            data=csv_bytes,
            file_name="financial_ai_votes.csv",
            mime="text/csv",
        )

    r1, r2 = st.columns(2)
    with r1:
        if st.button("응답만 초기화", use_container_width=True):
            with db_conn() as conn:
                conn.execute("DELETE FROM responses")
                conn.commit()
            st.success("모든 응답을 초기화했습니다.")
            st.rerun()

    with r2:
        confirm = st.checkbox("참여자 명단까지 초기화합니다", key="reset_people_confirm")
        if st.button("전체 초기화", use_container_width=True, disabled=not confirm):
            with db_conn() as conn:
                conn.execute("DELETE FROM responses")
                conn.execute("DELETE FROM participants")
                conn.execute(
                    """
                    UPDATE app_state
                    SET current_case=0, phase='pre', display_mode='waiting', updated_at=?
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
