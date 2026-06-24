"""
domains/payroll/email/service.py — Gmail SMTP 이메일 발송
"""
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path


SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "settings.json"


def get_smtp_config() -> dict:
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("smtp", {})
        except Exception:
            pass
    return {}


def save_smtp_config(config: dict) -> bool:
    try:
        data: dict = {}
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        data["smtp"] = config
        SETTINGS_PATH.parent.mkdir(exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def send_payslip_email(to_email: str, subject: str,
                       html_content: str, attachment_name: str) -> tuple[bool, str]:
    """
    Gmail SMTP로 급여명세서 HTML을 첨부파일로 발송.
    반환: (성공여부, 오류메시지)
    """
    cfg = get_smtp_config()
    sender    = cfg.get("sender_email", "")
    app_pw    = cfg.get("app_password", "")
    smtp_host = cfg.get("host", "smtp.gmail.com")
    smtp_port = int(cfg.get("port", 587))

    if not sender or not app_pw:
        return False, "Gmail SMTP 설정이 없습니다. 이메일 설정 탭에서 입력해주세요."

    try:
        msg = MIMEMultipart()
        msg["From"]    = sender
        msg["To"]      = to_email
        msg["Subject"] = subject

        body_html = f"""
        <html><body style="font-family:sans-serif;color:#1F1B1B">
          <p>안녕하세요,</p>
          <p>첨부 파일을 확인해주세요.</p>
          <p style="color:#9A918C;font-size:12px">본 이메일은 자동 발송됩니다.</p>
        </body></html>"""
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        # HTML 파일 첨부
        part = MIMEBase("application", "octet-stream")
        part.set_payload(html_content.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
        msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, app_pw)
            server.sendmail(sender, [to_email], msg.as_string())

        return True, ""
    except Exception as e:
        return False, str(e)


def render_email_settings():
    """이메일 설정 UI (급여명세서 탭 내부에서 호출)"""
    import streamlit as st
    from shared.utils import sec

    sec("Gmail SMTP 설정")
    st.markdown("""
    **Gmail 앱 비밀번호 발급 방법**
    1. Google 계정 → 보안 → 2단계 인증 활성화
    2. 보안 → 앱 비밀번호 → 앱 선택(메일) → 기기 선택(Windows) → 생성
    3. 생성된 16자리 앱 비밀번호를 아래에 입력
    """)

    cfg = get_smtp_config()
    with st.form("smtp_form"):
        sender_email = st.text_input("발신 Gmail 주소", value=cfg.get("sender_email", ""),
                                      key="smtp_sender")
        app_password = st.text_input("앱 비밀번호 (16자리)", type="password",
                                      value=cfg.get("app_password", ""), key="smtp_pw")
        col1, col2 = st.columns(2)
        smtp_host = col1.text_input("SMTP 호스트", value=cfg.get("host", "smtp.gmail.com"), key="smtp_host")
        smtp_port = col2.number_input("포트", min_value=1, max_value=65535,
                                       value=int(cfg.get("port", 587)), key="smtp_port")
        if st.form_submit_button("저장", type="primary"):
            ok = save_smtp_config({
                "sender_email": sender_email.strip(),
                "app_password": app_password.strip(),
                "host": smtp_host.strip(),
                "port": int(smtp_port),
            })
            st.success("✅ SMTP 설정 저장 완료") if ok else st.error("저장 실패")

    # 테스트 발송
    st.divider()
    sec("테스트 발송")
    test_email = st.text_input("수신 이메일 (테스트용)", key="test_email_addr")
    if st.button("테스트 이메일 발송", key="test_smtp_btn"):
        if test_email:
            ok, err = send_payslip_email(
                to_email=test_email,
                subject="[WebSettle] SMTP 테스트 메일",
                html_content="<html><body><h2>테스트 성공!</h2><p>WebSettle 급여 시스템 이메일 연동이 정상 작동합니다.</p></body></html>",
                attachment_name="test.html",
            )
            if ok:
                st.success(f"✅ {test_email} 으로 발송 완료!")
            else:
                st.error(f"발송 실패: {err}")
        else:
            st.error("수신 이메일을 입력하세요.")
