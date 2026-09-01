"""Build the approval-gated Zorva one-page overview PDF."""

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "zorva-controlled-pilot-overview-draft.pdf"

TEAL = HexColor("#0F766E")
TEAL_DARK = HexColor("#115E59")
CHARCOAL = HexColor("#1E293B")
SLATE = HexColor("#475569")
MUTED = HexColor("#64748B")
PALE = HexColor("#F0FDFA")
LINE = HexColor("#CBD5E1")
AMBER = HexColor("#B45309")


def wrapped_lines(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def paragraph(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 9.1,
    leading: float = 12.6,
    color=SLATE,
) -> float:
    c.setFont(font, size)
    c.setFillColor(color)
    for line in wrapped_lines(text, font, size, width):
        c.drawString(x, y, line)
        y -= leading
    return y


def bullet(c: canvas.Canvas, text: str, x: float, y: float, width: float) -> float:
    c.setFillColor(TEAL)
    c.circle(x + 2.5, y + 3, 2.2, fill=1, stroke=0)
    return paragraph(c, text, x + 12, y, width - 12, size=8.6, leading=11.5)


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=letter, pageCompression=1, invariant=1)
    width, height = letter
    c.setTitle("Zorva controlled pilot overview - draft")
    c.setAuthor("Cameron Ashley")
    c.setSubject("Approval-gated overview of Zorva's Alberta AHCIP review direction")

    margin = 42
    usable = width - margin * 2

    c.setFillColor(CHARCOAL)
    c.rect(0, height - 92, width, 92, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.roundRect(margin, height - 68, 28, 28, 7, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 19)
    c.drawCentredString(margin + 14, height - 59, "Z")
    c.setFont("Helvetica-Bold", 23)
    c.drawString(margin + 38, height - 60, "Zorva")
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(HexColor("#99F6E4"))
    c.drawRightString(
        width - margin, height - 52, "DRAFT - NOT APPROVED FOR EXTERNAL USE"
    )
    c.setFont("Helvetica", 7.5)
    c.setFillColor(HexColor("#CBD5E1"))
    c.drawRightString(
        width - margin, height - 67, "Owner: Cameron Ashley | Offer and claims pending"
    )

    y = height - 124
    c.setFillColor(CHARCOAL)
    c.setFont("Helvetica-Bold", 21)
    c.drawString(margin, y, "A practical review step before an")
    y -= 25
    c.setFillColor(TEAL_DARK)
    c.drawString(margin, y, "Alberta claim is submitted")
    y -= 22
    y = paragraph(
        c,
        "Zorva is designed for Alberta primary-care billing teams that want a more consistent way to examine potential AHCIP claim problems before submission. The clinic's billing team keeps the final decision about what, if anything, is submitted.",
        margin,
        y,
        usable,
        size=10.1,
        leading=14.1,
        color=SLATE,
    )

    y -= 9
    c.setStrokeColor(LINE)
    c.line(margin, y, width - margin, y)
    y -= 24

    left_w = 316
    gap = 24
    right_x = margin + left_w + gap
    right_w = usable - left_w - gap

    c.setFillColor(CHARCOAL)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "A three-step human review path")
    y_left = y - 20
    steps = [
        (
            "1",
            "Bring an encounter into review",
            "Start with the narrative and billed services the team wants to assess.",
        ),
        (
            "2",
            "Review the available context",
            "Place relevant billing context and supporting references beside the encounter.",
        ),
        (
            "3",
            "Make the decision as a team",
            "Accept, correct, dismiss, or investigate; Zorva does not submit the claim.",
        ),
    ]
    for number, heading, body in steps:
        c.setFillColor(PALE)
        c.roundRect(margin, y_left - 39, left_w, 48, 7, fill=1, stroke=0)
        c.setFillColor(TEAL)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin + 11, y_left - 8, number)
        c.setFillColor(CHARCOAL)
        c.setFont("Helvetica-Bold", 9.1)
        c.drawString(margin + 31, y_left - 5, heading)
        paragraph(c, body, margin + 31, y_left - 18, left_w - 43, size=7.8, leading=9.8)
        y_left -= 58

    c.setFillColor(CHARCOAL)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(right_x, y, "Controlled pilot fit")
    y_right = y - 20
    for item in [
        "Alberta primary-care team using AHCIP",
        "Named billing-workflow owner",
        "Human reviewer retains the final decision",
        "Privacy and onboarding review before clinic data",
    ]:
        y_right = bullet(c, item, right_x, y_right, right_w)
        y_right -= 7

    y = min(y_left, y_right) - 7
    c.setFillColor(HexColor("#FFF7ED"))
    c.roundRect(margin, y - 58, usable, 66, 7, fill=1, stroke=0)
    c.setFillColor(AMBER)
    c.setFont("Helvetica-Bold", 9.3)
    c.drawString(margin + 13, y - 12, "Deliberately not promised")
    paragraph(
        c,
        "Pilot duration, volume, pricing, success criteria, privacy terms, support commitments, customer outcomes, certifications, and financial results remain unapproved and are omitted.",
        margin + 13,
        y - 27,
        usable - 26,
        size=8.2,
        leading=10.5,
        color=SLATE,
    )
    y -= 86

    c.setFillColor(CHARCOAL)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, "Start with your current workflow")
    y -= 17
    y = paragraph(
        c,
        "Discuss where review effort is concentrated today, what information the team needs before submission, and whether a controlled evaluation is an appropriate fit. This is a request for a conversation, not self-serve production access.",
        margin,
        y,
        usable,
        size=9,
        leading=12.2,
    )
    y -= 11

    contact_url = "https://zorva.ashbi.ca/contact?utm_source=one_page&utm_medium=private_share&utm_campaign=controlled_alberta_launch_v1"
    how_url = "https://zorva.ashbi.ca/how-it-works?utm_source=one_page&utm_medium=private_share&utm_campaign=controlled_alberta_launch_v1"
    c.setFillColor(TEAL)
    c.roundRect(margin, y - 31, 168, 31, 6, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 9.5)
    c.drawCentredString(margin + 84, y - 20, "Start a conversation")
    c.linkURL(contact_url, (margin, y - 31, margin + 168, y), relative=0)
    c.setFillColor(TEAL_DARK)
    c.setFont("Helvetica-Bold", 9.2)
    c.drawString(margin + 187, y - 20, "Read how the review path works")
    c.linkURL(how_url, (margin + 184, y - 31, width - margin, y), relative=0)

    footer_y = 42
    c.setStrokeColor(LINE)
    c.line(margin, footer_y + 19, width - margin, footer_y + 19)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawString(
        margin,
        footer_y + 7,
        "Claim sources: docs/launch-kit/CLAIM_MANIFEST.json | ZC-001 through ZC-005",
    )
    c.drawRightString(width - margin, footer_y + 7, "2026-09-01 | v1 draft")
    c.setFont("Helvetica", 6.5)
    c.drawString(
        margin,
        footer_y - 3,
        "No autonomous submission, financial outcome, certification, or regulated-status representation is made.",
    )

    c.showPage()
    c.save()
    print(OUTPUT)


if __name__ == "__main__":
    build()
