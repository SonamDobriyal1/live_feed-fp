#!/usr/bin/env python3
"""Generate client-facing deployment status Word report."""

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "Client_Deployment_Status_Report.docx"


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0x1A, 0x37, 0x5E)


def add_bullet(doc: Document, text: str, bold_prefix: str = "") -> None:
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        run = p.add_run(bold_prefix)
        run.bold = True
        p.add_run(text)
    else:
        p.add_run(text)


def build() -> Document:
    doc = Document()

    # Title block
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Violence Detection System\n")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = RGBColor(0x1A, 0x37, 0x5E)
    sub = title.add_run("Deployment Status & Infrastructure Recommendations")
    sub.font.size = Pt(14)
    sub.font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Report Date: {date.today().strftime('%d %B %Y')}\n").italic = True
    meta.add_run("Prepared for: Client Review\n").italic = True
    meta.add_run("Prepared by: Development Team").italic = True

    doc.add_paragraph()

    # 1. Executive Summary
    add_heading(doc, "1. Executive Summary")
    doc.add_paragraph(
        "We have successfully built and tested a live CCTV violence detection system that "
        "monitors the CP Plus camera feed, runs AI-based violence classification, sends SMS "
        "alerts via Twilio, and logs detections to Supabase. The application works correctly "
        "when running on the local network where the camera is installed."
    )
    doc.add_paragraph(
        "However, cloud deployment on Render (Singapore region) cannot maintain a stable "
        "connection to the on-premises camera. The root cause is network accessibility: the "
        "camera's streaming port is not exposed to the public internet in a way that allows "
        "Render's servers to connect reliably. This report outlines the issue, recommended "
        "solutions, and infrastructure changes required to proceed."
    )

    # 2. What's Working
    add_heading(doc, "2. Completed & Verified")
    items_done = [
        "Live RTSPS camera feed integration (CP Plus / Dahua protocol)",
        "YOLOv8 violence detection model integrated and tuned (~95% validation accuracy)",
        "SMS alert delivery via Twilio (tested successfully)",
        "Supabase database logging for violence events (tested successfully)",
        "Docker-based deployment package ready for Render Background Worker",
        "Headless production mode (no UI on server — ML + alerts only)",
    ]
    for item in items_done:
        add_bullet(doc, item)

    # 3. Current Blocker
    add_heading(doc, "3. Current Deployment Blocker")
    doc.add_paragraph(
        "When the application is deployed to Render's cloud infrastructure, it cannot "
        "sustain a live video stream from the camera. Investigation confirmed the following:"
    )

    add_heading(doc, "3.1 Port & Network Accessibility", level=2)
    add_bullet(doc, "The camera streams video over RTSPS (secure RTSP) on port 554.", bold_prefix="Port 554: ")
    add_bullet(doc, "Render's cloud servers (hosted in Singapore) attempt to connect to the camera over the public internet.", bold_prefix="Cloud access: ")
    add_bullet(doc, "The camera is on a local/residential or office network and does not accept sustained inbound connections from external cloud IPs.", bold_prefix="Network restriction: ")
    add_bullet(doc, "Port 554 is not open/forwarded on the client's router/firewall for external access, which is standard security practice for CCTV systems.", bold_prefix="Firewall: ")

    doc.add_paragraph(
        "In summary: the AI application is ready, but the camera is designed for local network "
        "access only. Cloud servers cannot reach it without additional networking setup."
    )

    # 4. Recommended Solution
    add_heading(doc, "4. Recommended Solution: Cloudflare Tunnel")
    doc.add_paragraph(
        "To enable cloud-based monitoring without exposing the camera directly to the internet, "
        "we recommend implementing Cloudflare Tunnel (formerly Argo Tunnel). This is an industry-standard "
        "approach for securely connecting on-premises devices to cloud services."
    )

    add_heading(doc, "4.1 How Cloudflare Tunnel Works", level=2)
    steps = [
        "A small Cloudflare Tunnel agent (cloudflared) is installed on a device on the same network as the camera (e.g., a local PC, NUC, or Raspberry Pi).",
        "The agent creates a secure outbound connection to Cloudflare — no inbound port forwarding is required on the router.",
        "The camera stream is relayed through this encrypted tunnel to the cloud application on Render.",
        "The camera remains protected behind the firewall; only authenticated tunnel traffic is permitted.",
    ]
    for i, step in enumerate(steps, 1):
        doc.add_paragraph(f"{i}. {step}", style="List Number")

    add_heading(doc, "4.2 Benefits", level=2)
    for benefit in [
        "No need to open port 554 on the public internet (reduces security risk)",
        "Encrypted end-to-end connection",
        "Works with existing CP Plus camera — no camera replacement required",
        "Reliable connection for 24/7 cloud monitoring",
    ]:
        add_bullet(doc, benefit)

    add_heading(doc, "4.3 Requirements from Client", level=2)
    for req in [
        "A Cloudflare account (free tier is sufficient to start; paid plan optional for advanced features)",
        "A always-on local device on the same network as the camera to run the tunnel agent",
        "Client IT/network administrator approval to install cloudflared on the local network",
        "Approximately 1–2 hours of setup and testing time",
    ]:
        add_bullet(doc, req)

    # 5. Render Paid Plan
    add_heading(doc, "5. Render Hosting — Paid Plan Required")
    doc.add_paragraph(
        "The application is deployed on Render as a Background Worker for continuous 24/7 "
        "CCTV monitoring. The free tier on Render is not suitable for this use case for the "
        "following reasons:"
    )

    add_heading(doc, "5.1 Free Tier Limitations", level=2)
    for lim in [
        "Free Background Workers spin down after inactivity and have limited monthly runtime hours",
        "Violence detection requires continuous processing — the worker must run 24/7 without interruption",
        "Free tier has been exceeded / is insufficient for production CCTV monitoring",
        "Service reliability and uptime cannot be guaranteed on the free plan",
    ]:
        add_bullet(doc, lim)

    add_heading(doc, "5.2 Recommended Plan", level=2)
    doc.add_paragraph(
        "We recommend upgrading to the Render Starter plan (approximately $7/month per worker) "
        "for the violence monitoring Background Worker. This provides:"
    )
    for feat in [
        "Always-on service — no sleep or spin-down",
        "Sufficient CPU and memory for AI inference + ffmpeg video decoding",
        "Reliable 24/7 uptime for production monitoring",
        "Priority support and stable deployment pipeline",
    ]:
        add_bullet(doc, feat)

    doc.add_paragraph(
        "Note: Render billing is managed directly by the client on render.com. "
        "We can assist with configuration after the plan is upgraded."
    )

    # 6. Architecture diagram (text)
    add_heading(doc, "6. Proposed Architecture (After Tunnel Setup)")
    arch = doc.add_paragraph()
    arch.add_run(
        "Camera (Local Network)\n"
        "       │\n"
        "       ▼\n"
        "Cloudflare Tunnel Agent (cloudflared on local device)\n"
        "       │  encrypted outbound tunnel\n"
        "       ▼\n"
        "Cloudflare Edge\n"
        "       │\n"
        "       ▼\n"
        "Render Background Worker (Violence Detection + SMS + Supabase)\n"
        "       │\n"
        "       ├──► Twilio SMS Alerts\n"
        "       └──► Supabase Event Logging"
    ).font.name = "Courier New"

    # 7. Next Steps
    add_heading(doc, "7. Next Steps & Client Approvals Required")
    doc.add_paragraph("To move to production, we request the following approvals and actions:")
    next_steps = [
        ("Approve Cloudflare Tunnel approach", "Confirm client IT is willing to install cloudflared on a local network device"),
        ("Provide local hardware", "A PC, NUC, or Raspberry Pi on the same LAN as the camera (always powered on)"),
        ("Upgrade Render plan", "Upgrade violence-monitor worker to Render Starter plan (~$7/month)"),
        ("Cloudflare account setup", "Create or provide access to a Cloudflare account for tunnel configuration"),
        ("Schedule setup session", "1–2 hour remote session to configure tunnel and verify end-to-end alerts"),
    ]
    for i, (action, detail) in enumerate(next_steps, 1):
        p = doc.add_paragraph(style="List Number")
        p.add_run(f"{action}. ").bold = True
        p.add_run(detail)

    # 8. Timeline
    add_heading(doc, "8. Estimated Timeline")
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Task"
    hdr[1].text = "Estimated Duration"
    rows = [
        ("Render plan upgrade", "Same day (client action)"),
        ("Cloudflare account + tunnel setup", "1–2 hours"),
        ("Integration testing (stream + alerts)", "2–4 hours"),
        ("Production go-live", "Same day after successful test"),
    ]
    for task, duration in rows:
        row = table.add_row().cells
        row[0].text = task
        row[1].text = duration

    # 9. Summary
    add_heading(doc, "9. Summary")
    doc.add_paragraph(
        "The violence detection software is complete and tested. The remaining work is "
        "infrastructure — not application development. Two client-side actions are required "
        "before production deployment:"
    )
    summary = doc.add_paragraph()
    summary.add_run("1. ").bold = True
    summary.add_run("Implement Cloudflare Tunnel to securely expose the camera stream to the cloud.\n")
    summary.add_run("2. ").bold = True
    summary.add_run("Upgrade Render to a paid Starter plan for 24/7 continuous monitoring.\n\n")
    summary.add_run(
        "Once these are in place, we can complete setup and deliver a fully operational "
        "production system with live violence detection, SMS alerts, and event logging."
    )

    # Footer
    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("— End of Report —")
    run.italic = True
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    return doc


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = build()
    doc.save(OUTPUT)
    print(f"Created: {OUTPUT}")


if __name__ == "__main__":
    main()
