"""Renderizador de currículo em PDF A4."""

from __future__ import annotations

from fpdf import FPDF

from trampo_radar.config import ContactConfig, ProfileConfig
from trampo_radar.schemas.job import GeneratedResume

ACCENT_COLOR = (37, 97, 174)  # Azul LinkedIn
GRAY_COLOR = (100, 110, 120)
LINK_COLOR = (27, 99, 228)
BLACK_COLOR = (0, 0, 0)


def _latin1_safe(text: str) -> str:
    """Converte caracteres especiais fora do latin-1 para equivalentes seguros nas fontes core."""
    replacements = {
        "\u2022": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def format_contact(contact: ContactConfig) -> str:
    parts = [p for p in (contact.email, contact.phone, contact.linkedin, contact.github) if p]
    return "  |  ".join(parts)


def render_resume_pdf(profile: ProfileConfig, resume: GeneratedResume) -> bytes:
    """Gera os bytes de um arquivo PDF A4 com o currículo adaptado para a vaga."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(left=12, top=12, right=12)
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    # Cabeçalho do Candidato
    pdf.set_font("Helvetica", style="B", size=18)
    pdf.set_text_color(*BLACK_COLOR)
    pdf.multi_cell(0, 8, _latin1_safe(profile.name or "Candidato"), new_x="LMARGIN", new_y="NEXT")

    if profile.job_title:
        pdf.set_font("Helvetica", style="I", size=11)
        pdf.set_text_color(*GRAY_COLOR)
        pdf.multi_cell(0, 6, _latin1_safe(profile.job_title), new_x="LMARGIN", new_y="NEXT")

    contact_line = format_contact(profile.contact)
    if contact_line:
        pdf.set_font("Helvetica", size=9)
        pdf.set_text_color(*GRAY_COLOR)
        pdf.multi_cell(0, 5, _latin1_safe(contact_line), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)
    pdf.set_draw_color(*ACCENT_COLOR)
    pdf.set_line_width(0.6)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y())
    pdf.ln(3)

    def add_section_title(title: str) -> None:
        pdf.ln(2)
        pdf.set_font("Helvetica", style="B", size=11)
        pdf.set_text_color(*ACCENT_COLOR)
        pdf.cell(0, 6, _latin1_safe(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*ACCENT_COLOR)
        pdf.set_line_width(0.2)
        pdf.line(12, pdf.get_y(), 198, pdf.get_y())
        pdf.ln(2)

    # Resumo
    if resume.resumo:
        add_section_title("RESUMO")
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(*BLACK_COLOR)
        pdf.multi_cell(0, 5, _latin1_safe(resume.resumo), new_x="LMARGIN", new_y="NEXT")

    # Habilidades
    if resume.habilidades:
        add_section_title("HABILIDADES")
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(*BLACK_COLOR)
        for skill in resume.habilidades:
            pdf.multi_cell(0, 5, _latin1_safe(f"- {skill}"), new_x="LMARGIN", new_y="NEXT")

    # Experiência
    if resume.experiencia:
        add_section_title("EXPERIÊNCIA")
        for exp in resume.experiencia:
            role_title = f"{exp.cargo} - {exp.empresa}" if exp.empresa else exp.cargo
            pdf.set_font("Helvetica", style="B", size=10)
            pdf.set_text_color(*BLACK_COLOR)
            pdf.multi_cell(0, 5, _latin1_safe(role_title), new_x="LMARGIN", new_y="NEXT")

            if exp.periodo:
                pdf.set_font("Helvetica", style="I", size=9)
                pdf.set_text_color(*GRAY_COLOR)
                pdf.multi_cell(0, 4.5, _latin1_safe(exp.periodo), new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", size=10)
            pdf.set_text_color(*BLACK_COLOR)
            for desc in exp.descricao:
                pdf.multi_cell(0, 5, _latin1_safe(f"- {desc}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    # Projetos
    if resume.projetos:
        add_section_title("PROJETOS")
        for proj in resume.projetos:
            pdf.set_font("Helvetica", style="B", size=10)
            pdf.set_text_color(*BLACK_COLOR)
            pdf.multi_cell(0, 5, _latin1_safe(proj.nome), new_x="LMARGIN", new_y="NEXT")

            if proj.link:
                pdf.set_font("Helvetica", size=9)
                pdf.set_text_color(*LINK_COLOR)
                pdf.multi_cell(
                    0, 4.5, _latin1_safe(proj.link), link=proj.link, new_x="LMARGIN", new_y="NEXT"
                )

            if proj.descricao:
                pdf.set_font("Helvetica", size=10)
                pdf.set_text_color(*BLACK_COLOR)
                pdf.multi_cell(0, 5, _latin1_safe(proj.descricao), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    # Formação
    if resume.formacao:
        add_section_title("FORMAÇÃO")
        for edu in resume.formacao:
            edu_title = f"{edu.curso} - {edu.instituicao}" if edu.instituicao else edu.curso
            pdf.set_font("Helvetica", style="B", size=10)
            pdf.set_text_color(*BLACK_COLOR)
            pdf.multi_cell(0, 5, _latin1_safe(edu_title), new_x="LMARGIN", new_y="NEXT")

            if edu.periodo:
                pdf.set_font("Helvetica", style="I", size=9)
                pdf.set_text_color(*GRAY_COLOR)
                pdf.multi_cell(0, 4.5, _latin1_safe(edu.periodo), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    # Idiomas
    if resume.idiomas:
        add_section_title("IDIOMAS")
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(*BLACK_COLOR)
        langs = [
            f"{item.idioma} ({item.nivel})" if item.nivel else item.idioma
            for item in resume.idiomas
        ]
        pdf.multi_cell(0, 5, _latin1_safe("  |  ".join(langs)), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
