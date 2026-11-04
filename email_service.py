import smtplib
import ssl
from email.message import EmailMessage


def send_certificate(
    sender,
    app_password,
    recipient,
    subject,
    body,
    certificate_pdf,
    filename,
):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    message.add_attachment(
        certificate_pdf,
        maintype="application",
        subtype="pdf",
        filename=filename,
    )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        context=ssl.create_default_context(),
        timeout=30,
    ) as server:
        server.login(sender, app_password)
        refused = server.send_message(message)

        if refused:
            raise RuntimeError("The recipient was rejected.")