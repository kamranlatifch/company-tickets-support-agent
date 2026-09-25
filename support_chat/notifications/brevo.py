import httpx

from support_chat.config import BREVO_API_KEY, BREVO_FROM_EMAIL, BREVO_FROM_NAME

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def send_resolution_email(to_email: str, subject: str, body: str) -> dict:
    if not BREVO_API_KEY:
        # No key configured — log instead of failing, so the rest of the app works.
        print(f"[email stub] to={to_email} subject={subject!r}\n{body}")
        return {"provider": "Brevo", "status": "stubbed", "to": to_email}

    payload = {
        "sender": {"name": BREVO_FROM_NAME, "email": BREVO_FROM_EMAIL},
        "to": [{"email": to_email}],
        "replyTo": {"email": BREVO_FROM_EMAIL},
        "subject": subject,
        "textContent": body,
    }
    try:
        response = httpx.post(
            _BREVO_URL,
            json=payload,
            headers={"api-key": BREVO_API_KEY, "accept": "application/json"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return {"provider": "Brevo", "status": "failed", "to": to_email, "status_code": None, "error": str(exc)}

    if response.status_code >= 400:
        return {
            "provider": "Brevo",
            "status": "failed",
            "to": to_email,
            "status_code": response.status_code,
            "error": response.text,
        }
    return {"provider": "Brevo", "status": "sent", "to": to_email, "status_code": response.status_code}
