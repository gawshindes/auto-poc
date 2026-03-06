#!/usr/bin/env python3
"""
One-time script — generates test-trascripts/spiky_sample.pdf from the .txt source.

Usage:
    python create_sample_transcripts.py
"""

from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("fpdf2 not installed. Run: pip install fpdf2")
    raise SystemExit(1)

SRC = Path("test-trascripts/spiky_sample.txt")
OUT = Path("test-trascripts/spiky_sample.pdf")


def build_pdf(src: Path, out: Path) -> None:
    text = src.read_text(encoding="utf-8")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    for line in text.splitlines():
        # Section headers (## ...) in bold
        if line.startswith("## "):
            pdf.set_font("Helvetica", style="B", size=11)
            pdf.multi_cell(0, 6, line[3:])
            pdf.set_font("Helvetica", size=10)
        # Horizontal rules
        elif line.strip() == "---":
            pdf.ln(2)
            pdf.set_draw_color(180, 180, 180)
            pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
            pdf.ln(3)
        # Empty lines
        elif line.strip() == "":
            pdf.ln(4)
        # Normal lines
        else:
            pdf.multi_cell(0, 5, line)

    pdf.output(str(out))
    print(f"Created: {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if not SRC.exists():
        print(f"Source file not found: {SRC}")
        raise SystemExit(1)
    build_pdf(SRC, OUT)
