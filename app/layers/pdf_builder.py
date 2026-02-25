"""
PDF builder — renders ProposalOutput into a PDF via WeasyPrint + Jinja2.
Output written to tmp/proposals/{session_id}.pdf.
Files are deleted when the session ends or times out.
"""
from __future__ import annotations

import logging
from pathlib import Path

import weasyprint
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config_loader import CompanyConfig
from app.models.output_models import ProposalOutput

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def build_pdf(
    proposal: ProposalOutput,
    company: CompanyConfig,
    session_id: str,
) -> str:
    """
    Render proposal to HTML and write a PDF to tmp/proposals/{session_id}.pdf.
    Returns the path to the written PDF file.
    Raises on any WeasyPrint or template error (caller triggers escalation).
    """
    template = _jinja_env.get_template("proposal.html")
    html_content = template.render(
        proposal=proposal,
        company=company,
        generated_at=proposal.generated_at,
    )

    output_path = Path(f"tmp/proposals/{session_id}.pdf")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    weasyprint.HTML(string=html_content).write_pdf(str(output_path))
    logger.info("PDF written: %s (%d bytes)", output_path, output_path.stat().st_size)

    return str(output_path)
