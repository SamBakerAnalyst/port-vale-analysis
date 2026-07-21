#!/usr/bin/env python3
"""Generate IT setup PDF for Port Vale Analysis Hub DNS configuration."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

OUTPUT = Path(__file__).resolve().parent / "Port-Vale-Analysis-Hub-IT-Setup.pdf"

SERVER_IP = "178.128.161.215"
DOMAIN = "analysis.port-vale.co.uk"
SUBDOMAIN = "analysis"


class ITGuidePDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self.set_auto_page_break(auto=True, margin=18)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 116, 139)
        self.cell(0, 8, "Port Vale FC  |  Analysis Hub  |  IT Setup Guide", align="L")
        self.ln(10)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title: str) -> None:
        self.ln(4)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(15, 23, 42)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(245, 197, 24)
        self.set_line_width(0.8)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def body(self, text: str) -> None:
        self.set_font("Helvetica", "", 11)
        self.set_text_color(30, 41, 59)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def bullet(self, text: str) -> None:
        self.set_font("Helvetica", "", 11)
        self.set_text_color(30, 41, 59)
        self.cell(6, 6, "-")
        self.multi_cell(0, 6, text)
        self.ln(1)

    def table_row(self, label: str, value: str, bold_value: bool = False) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(71, 85, 105)
        self.cell(45, 8, label)
        if bold_value:
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(15, 23, 42)
        else:
            self.set_font("Helvetica", "", 11)
            self.set_text_color(30, 41, 59)
        self.multi_cell(0, 8, value)
        self.ln(1)


def build_pdf() -> Path:
    pdf = ITGuidePDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    # Cover block
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 12, "Port Vale Analysis Hub", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 8, "IT setup guide - DNS configuration", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_fill_color(245, 197, 24)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, "  Action required: one DNS A record", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.body(
        "The Analysis department has deployed an internal football analysis platform for "
        "staff use (scouting, pre-match, post-match, squad planning, etc.). "
        "We require a single DNS record so staff can access the hub at a Port Vale subdomain."
    )

    pdf.section_title("1. DNS record required")
    pdf.table_row("Record type:", "A")
    pdf.table_row("Host / name:", SUBDOMAIN)
    pdf.table_row("Full hostname:", DOMAIN)
    pdf.table_row("Points to (IPv4):", SERVER_IP)
    pdf.table_row("TTL:", "Default (e.g. 3600) - no special value needed")
    pdf.ln(4)

    pdf.section_title("2. Where to add the record")
    pdf.body("Add the record wherever port-vale.co.uk DNS is currently managed:")
    pdf.ln(2)
    pdf.bullet("Cloudflare: DNS > Add record > Type A > Name analysis > IPv4 " + SERVER_IP)
    pdf.bullet("Domain registrar or other DNS panel: same A record details as above")
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(180, 83, 9)
    pdf.multi_cell(0, 6, "If using Cloudflare: set Proxy status to DNS only (grey cloud), not Proxied (orange cloud).")
    pdf.ln(4)

    pdf.section_title("3. What IT does not need to do")
    pdf.bullet("No hosting, VM, or server setup at the club")
    pdf.bullet("No SSL certificate - handled automatically on our server after DNS is live")
    pdf.bullet("No firewall changes, port forwarding, or internal network configuration")
    pdf.bullet("No email or Microsoft 365 changes at this stage")
    pdf.ln(2)

    pdf.section_title("4. How it works")
    pdf.body(
        "Staff open the subdomain in Chrome. DNS resolves to our cloud server in London "
        "(DigitalOcean). The application is password-protected and for internal staff use only."
    )
    pdf.ln(2)
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(51, 65, 85)
    pdf.multi_cell(
        0,
        5,
        "Staff browser  ->  " + DOMAIN + "  ->  DNS A record  ->  " + SERVER_IP + "\n"
        "                                                      ->  Analysis hub (password required)",
    )
    pdf.ln(6)

    pdf.section_title("5. Current status")
    pdf.table_row("Server:", "Live and running at " + SERVER_IP)
    pdf.table_row("Application:", "Deployed and password-protected")
    pdf.table_row("DNS:", "Waiting on A record (this request)")
    pdf.table_row("HTTPS on domain:", "Enabled by Analysis team after DNS propagates")
    pdf.ln(2)
    pdf.body(
        "Until DNS is live, staff can use the temporary address http://" + SERVER_IP + "/ "
        "(with login credentials provided separately by the Analysis team)."
    )

    pdf.section_title("6. After the DNS record is added")
    pdf.bullet("DNS propagation typically takes 15-60 minutes")
    pdf.bullet("The Analysis team will enable HTTPS at https://" + DOMAIN)
    pdf.bullet("No further IT action should be required")
    pdf.ln(2)

    pdf.section_title("7. Security summary")
    pdf.bullet("Access is restricted by username and password")
    pdf.bullet("Microsoft 365 single sign-on is planned as a future enhancement")
    pdf.bullet("Impect API credentials are stored on the application server only")
    pdf.bullet("Server: Ubuntu 24.04, Docker, London (DigitalOcean LON1)")
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, "Summary for IT", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 41, 59)
    pdf.multi_cell(
        0,
        6,
        "Please add an A record: " + DOMAIN + " -> " + SERVER_IP + "\n\n"
        "If using Cloudflare, use DNS only (grey cloud).\n\n"
        "Contact: Port Vale Analysis department for questions about the application.",
    )

    pdf.output(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    path = build_pdf()
    print(path)
