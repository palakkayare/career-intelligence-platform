"""
PDF rendering for invoices.

ReportLab rather than WeasyPrint: it is a pure-Python wheel with no system
libraries behind it, so it installs identically on a developer's laptop and
inside a slim Docker image. WeasyPrint would drag in cairo and pango.

The layout is built from the dict that invoice.generate_invoice_data()
already returns, so there is exactly one definition of what an invoice says.
"""

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# GST invoices are commonly retained for years, so the filename needs to be
# stable and self-describing rather than tied to a download timestamp.
FILENAME_TEMPLATE = "invoice-{number}.pdf"


def render_invoice_pdf(transaction):
    """
    Return the invoice for one successful transaction as PDF bytes.

    Raises ValueError for a transaction that has no invoice (mirroring
    generate_invoice_data), and ImportError if ReportLab is unavailable.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .invoice import generate_invoice_data

    data = generate_invoice_data(transaction)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Invoice {data['invoice_number']}",
        author=data["company"]["name"],
    )

    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "InvoiceHeading",
        parent=styles["Heading1"],
        fontSize=20,
        spaceAfter=2,
    )
    muted = ParagraphStyle(
        "Muted",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#666666"),
    )
    label = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#666666"),
        spaceAfter=2,
    )

    story = []

    # -- Header: who issued it, and which invoice this is ------------------
    story.append(Paragraph("INVOICE", heading))
    story.append(Paragraph(data["invoice_number"], muted))
    story.append(Spacer(1, 10 * mm))

    company = data["company"]
    story.append(Paragraph("FROM", label))
    story.append(Paragraph(f"<b>{company['name']}</b>", styles["Normal"]))
    story.append(Paragraph(company["address"], muted))
    # An unset GSTIN prints nothing rather than an empty label
    if company["gstin"]:
        story.append(Paragraph(f"GSTIN: {company['gstin']}", muted))
    story.append(Spacer(1, 6 * mm))

    customer = data["customer"]
    story.append(Paragraph("BILLED TO", label))
    story.append(Paragraph(f"<b>{customer['name']}</b>", styles["Normal"]))
    # invoice.py falls back to the email when no name is set, so printing
    # both lines unconditionally would repeat it
    if customer["name"] != customer["email"]:
        story.append(Paragraph(customer["email"], muted))
    story.append(Spacer(1, 4 * mm))

    story.append(
        Paragraph(
            f"Invoice date: {data['date']} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Paid on: {data['paid_at']}",
            muted,
        )
    )
    story.append(Spacer(1, 10 * mm))

    # -- Line items -------------------------------------------------------
    currency = data["currency"]
    rows = [["Description", "Billing period", f"Amount ({currency})"]]
    for item in data["items"]:
        rows.append(
            [
                item["description"],
                (item["period"] or "One-time").title(),
                item["amount"],
            ]
        )

    rows.append(["", "Subtotal", data["subtotal"]])
    rows.append(["", f"GST ({data['gst_rate']}%)", data["gst"]])
    rows.append(["", "Total paid", data["total"]])

    table = Table(rows, colWidths=[80 * mm, 45 * mm, 45 * mm])
    body_end = len(data["items"])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("ALIGN", (1, 1), (1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, body_end), 0.4, colors.HexColor("#dddddd")),
                # The total row is the number people look for, so it gets the weight
                ("FONTNAME", (1, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (1, -1), (-1, -1), 0.8, colors.HexColor("#333333")),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 12 * mm))

    # -- Payment reference ------------------------------------------------
    payment = data["payment"]
    story.append(Paragraph("PAYMENT", label))
    story.append(Paragraph(f"Method: {payment['method']}", muted))
    story.append(Paragraph(f"Payment ID: {payment['transaction_id']}", muted))
    story.append(Paragraph(f"Order ID: {payment['order_id']}", muted))
    story.append(Spacer(1, 10 * mm))

    story.append(
        Paragraph(
            "This is a computer-generated invoice and does not require a signature.",
            muted,
        )
    )

    doc.build(story)
    return buffer.getvalue()


def invoice_filename(transaction):
    from .invoice import generate_invoice_data

    return FILENAME_TEMPLATE.format(
        number=generate_invoice_data(transaction)["invoice_number"],
    )


def build_invoice_attachment(transaction):
    """
    (filename, content, mimetype) for emailing, or None.

    Never raises. A failed invoice must not stop the payment confirmation
    email from reaching the customer - the money has already moved, and the
    invoice stays downloadable from the account either way.
    """
    try:
        return (
            invoice_filename(transaction),
            render_invoice_pdf(transaction),
            "application/pdf",
        )
    except Exception:
        logger.exception(
            "Could not build invoice PDF for transaction %s",
            transaction.id,
        )
        return None
