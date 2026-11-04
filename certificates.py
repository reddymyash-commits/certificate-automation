from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import Paragraph


def create_certificate(student, template=None, background_bytes=None):
    """Create a certificate with an optional uploaded background."""
    output = BytesIO()

    # A4 landscape, in PDF points.
    width, height = 841.89, 595.28
    pdf = canvas.Canvas(output, pagesize=(width, height))

    if background_bytes:
        background = ImageReader(BytesIO(background_bytes))
        pdf.drawImage(
            background,
            0,
            0,
            width=width,
            height=height,
        )
    else:
        pdf.setFillColor(colors.white)
        pdf.rect(0, 0, width, height, fill=1, stroke=0)

    # Keep text away from the medal and ribbon on the right.
    center_x = width * 0.45
    text_width = width * 0.64

    def draw_text(text, top, size=18, bold=False, color="#14234B"):
        """Draw centered text; shrink longer text to fit."""
        safe_text = escape(str(text))

        for font_size in range(size, 7, -1):
            style = ParagraphStyle(
                "CertificateText",
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=font_size,
                leading=font_size * 1.25,
                alignment=TA_CENTER,
                textColor=colors.HexColor(color),
            )

            paragraph = Paragraph(safe_text, style)
            _, text_height = paragraph.wrap(text_width, height)

            if text_height <= 44:
                break

        paragraph.drawOn(
            pdf,
            center_x - text_width / 2,
            height - top - text_height,
        )

    draw_text("CERTIFICATE", top=95, size=32, bold=True)

    draw_text(
        student.get("Certificate Type", ""),
        top=140,
        size=21,
    )

    draw_text(
        "This certificate is presented to",
        top=184,
        size=16,
    )

    draw_text(
        student.get("Name", ""),
        top=218,
        size=30,
        bold=True,
    )

    draw_text(
        f'Event: {student.get("Event", "")}',
        top=278,
        size=20,
    )

    if student.get("Achievement"):
        draw_text(
            student["Achievement"],
            top=325,
            size=16,
        )

    if student.get("Date"):
        draw_text(
            f'Date: {student["Date"]}',
            top=385,
            size=14,
        )

    pdf.showPage()
    pdf.save()

    return output.getvalue()