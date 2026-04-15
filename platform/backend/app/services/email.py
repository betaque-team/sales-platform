"""Email sending service using SMTP."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_email(
    to: list[str],
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> bool:
    """Send an email via SMTP. Returns True on success."""
    settings = get_settings()

    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning("SMTP not configured — skipping email send")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)

        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)

        server.sendmail(settings.smtp_from_email, to, msg.as_string())
        server.quit()
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)
        return False


def build_job_alert_html(jobs: list[dict], app_url: str) -> str:
    """Build an HTML email body for job alert notifications."""
    rows = ""
    for j in jobs[:20]:
        score = j["relevance_score"]
        color = "#16a34a" if score >= 70 else "#ca8a04" if score >= 50 else "#dc2626"
        cluster = (j.get("role_cluster") or "other").upper()
        geo = (j.get("geography_bucket") or "").replace("_", " ").title()
        salary = f" &middot; {j['salary_range']}" if j.get("salary_range") else ""

        rows += f"""
        <tr>
          <td style="padding:10px 12px; border-bottom:1px solid #e5e7eb;">
            <a href="{app_url}/jobs/{j['id']}" style="color:#1d4ed8; font-weight:600; text-decoration:none;">{j['title']}</a>
            <br><span style="color:#6b7280; font-size:13px;">{j['company_name']} &middot; {cluster}{salary}</span>
          </td>
          <td style="padding:10px 12px; border-bottom:1px solid #e5e7eb; text-align:center;">
            <span style="color:{color}; font-weight:700;">{score}</span>
          </td>
          <td style="padding:10px 12px; border-bottom:1px solid #e5e7eb; color:#6b7280; font-size:13px;">{geo}</td>
        </tr>"""

    overflow = len(jobs) - 20
    overflow_note = f"<p style='color:#6b7280; font-size:13px; margin-top:12px;'>+{overflow} more jobs matching your criteria</p>" if overflow > 0 else ""

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; max-width:640px; margin:0 auto;">
      <div style="background:#1e3a5f; color:white; padding:20px 24px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0; font-size:18px;">🚀 {len(jobs)} New Job{'s' if len(jobs) != 1 else ''} Found</h2>
        <p style="margin:4px 0 0; opacity:0.8; font-size:13px;">Sales Platform Job Alert</p>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; border-radius:0 0 8px 8px; padding:16px;">
        <table style="width:100%; border-collapse:collapse;">
          <thead>
            <tr style="background:#f9fafb;">
              <th style="padding:8px 12px; text-align:left; font-size:12px; color:#6b7280; text-transform:uppercase;">Job</th>
              <th style="padding:8px 12px; text-align:center; font-size:12px; color:#6b7280; text-transform:uppercase;">Score</th>
              <th style="padding:8px 12px; text-align:left; font-size:12px; color:#6b7280; text-transform:uppercase;">Location</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        {overflow_note}
        <div style="margin-top:20px; text-align:center;">
          <a href="{app_url}/jobs?role_cluster=relevant" style="display:inline-block; background:#1e3a5f; color:white; padding:10px 24px; border-radius:6px; text-decoration:none; font-weight:600;">View All Jobs</a>
        </div>
      </div>
      <p style="color:#9ca3af; font-size:11px; text-align:center; margin-top:12px;">Sent by Sales Platform &middot; Manage alerts in Settings</p>
    </div>"""


def build_job_alert_text(jobs: list[dict], app_url: str) -> str:
    """Build a plain-text email body for job alerts."""
    lines = [f"{len(jobs)} New Job{'s' if len(jobs) != 1 else ''} Found", "=" * 40, ""]
    for j in jobs[:20]:
        cluster = (j.get("role_cluster") or "other").upper()
        lines.append(f"- {j['title']} at {j['company_name']} (Score: {j['relevance_score']}, {cluster})")
        lines.append(f"  {app_url}/jobs/{j['id']}")
        lines.append("")
    if len(jobs) > 20:
        lines.append(f"+{len(jobs) - 20} more jobs")
    lines.append(f"\nView all: {app_url}/jobs?role_cluster=relevant")
    return "\n".join(lines)
