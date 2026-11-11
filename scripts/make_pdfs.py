"""Render the two synthetic manuals to PDF, to demonstrate PDF ingestion."""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

root = Path(__file__).resolve().parent.parent / "data" / "manuals"
styles = getSampleStyleSheet()
for v in ("v1", "v2"):
    lines = (root / f"manual_{v}.txt").read_text().splitlines()
    story = []
    for ln in lines:
        story.append(Spacer(1, 8) if not ln.strip() else Paragraph(ln.replace("&", "&amp;"), styles["BodyText"]))
    SimpleDocTemplate(str(root / f"manual_{v}.pdf"), pagesize=A4).build(story)
    print("wrote", root / f"manual_{v}.pdf")
