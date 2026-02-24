"""
CV checklist extractor.

Parses NHS/DWP job descriptions to extract:
  1. Person specification criteria (Essential vs Desirable)
  2. Key terms and qualifications the CV should mention
  3. A structured checklist the user can review before submitting

Works entirely without LLM — uses regex, heuristics, and a curated
vocabulary of NHS-domain terms.
"""

import re
from collections import OrderedDict


# ── NHS domain vocabulary ──────────────────────────────────────────
# These are terms that, when found in a JD, should be flagged as
# things the CV needs to mention. Grouped by category.

NHS_KEYWORDS = {
    'registrations': [
        'NMC', 'GMC', 'GPhC', 'HCPC', 'GDC', 'GOC', 'GSCC',
        'registered nurse', 'registered practitioner',
        'professional registration', 'active registration',
        'PIN number', 'revalidation',
    ],
    'qualifications': [
        'degree', 'diploma', 'NVQ', 'QCF', 'foundation degree',
        'masters', 'MSc', 'BSc', 'PhD', 'postgraduate',
        'ENB 998', 'mentorship', 'PGCE', 'teaching qualification',
        'prescribing qualification', 'non-medical prescriber',
        'ALS', 'BLS', 'ILS', 'EPALS', 'NLS', 'ATLS', 'PALS',
        'PRINCE2', 'ITIL', 'Six Sigma',
        'Care Certificate', 'apprenticeship',
        'Level 2', 'Level 3', 'Level 4', 'Level 5',
    ],
    'clinical_skills': [
        'cannulation', 'venepuncture', 'phlebotomy',
        'catheterisation', 'catheter', 'wound care', 'wound management',
        'tracheostomy', 'suctioning', 'PEG feeding',
        'medication administration', 'drug administration',
        'ECG', 'cardiac monitoring', 'telemetry',
        'vital signs', 'NEWS', 'NEWS2', 'early warning score',
        'blood glucose monitoring', 'insulin administration',
        'manual handling', 'moving and handling',
        'infection control', 'aseptic technique',
        'safeguarding', 'Mental Capacity Act', 'DoLS', 'MCA',
        'risk assessment', 'care planning', 'care plan',
        'clinical audit', 'clinical governance',
        'triage', 'assessment', 'discharge planning',
    ],
    'systems_and_frameworks': [
        'SystmOne', 'EMIS', 'EPR', 'electronic patient record',
        'Lorenzo', 'Cerner', 'Meditech', 'RiO',
        'Microsoft Office', 'Excel', 'Word', 'PowerPoint',
        'NHS Spine', 'ESR', 'e-Roster', 'Healthroster',
        'CQC', 'NICE', 'NHSE', 'NHS England',
        'Agenda for Change', 'AfC',
    ],
    'soft_skills': [
        'leadership', 'management experience', 'team leader',
        'communication skills', 'interpersonal',
        'time management', 'organisational skills',
        'problem solving', 'decision making',
        'multidisciplinary', 'MDT',
        'patient-centred', 'person-centred',
        'empathy', 'compassion', 'resilience',
        'flexible', 'adaptable',
        'mentoring', 'supervision', 'preceptorship',
        'teaching', 'training',
        'audit', 'quality improvement', 'service improvement',
        'evidence-based practice', 'research',
        'budget management', 'resource management',
    ],
    'compliance_and_checks': [
        'DBS', 'enhanced DBS', 'disclosure and barring',
        'occupational health', 'immunisation',
        'right to work', 'Fit and Proper Person',
        'mandatory training', 'statutory training',
    ],
}


def extract_person_spec(job_description):
    """
    Parse the person specification from a job description.

    Returns a dict:
    {
        'essential': ['criterion 1', 'criterion 2', ...],
        'desirable': ['criterion 1', ...],
        'unparsed_sections': {'Section Name': 'raw text', ...}
    }
    """
    if not job_description:
        return {'essential': [], 'desirable': [], 'unparsed_sections': {}}

    text = job_description

    essential = []
    desirable = []
    unparsed_sections = OrderedDict()

    # Strategy 1: Look for explicit "Essential" and "Desirable" sections
    # These are extremely common in NHS person specifications
    essential_pattern = re.compile(
        r'(?:^|\n)\s*(?:essential|essential criteria|essential requirements)\s*[:\-]?\s*\n'
        r'(.*?)'
        r'(?=\n\s*(?:desirable|desirable criteria|additional|$))',
        re.IGNORECASE | re.DOTALL
    )
    desirable_pattern = re.compile(
        r'(?:^|\n)\s*(?:desirable|desirable criteria|desirable requirements)\s*[:\-]?\s*\n'
        r'(.*?)'
        r'(?=\n\s*(?:essential|additional|about|how to apply|closing|$))',
        re.IGNORECASE | re.DOTALL
    )

    essential_match = essential_pattern.search(text)
    desirable_match = desirable_pattern.search(text)

    if essential_match:
        essential = _extract_bullet_points(essential_match.group(1))
    if desirable_match:
        desirable = _extract_bullet_points(desirable_match.group(1))

    # Strategy 2: Look for labelled lines like "Essential: ..." or "(E)" / "(D)"
    if not essential:
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            # Lines ending with (E) or (Essential) or marked Essential:
            if re.search(r'\(E\)\s*$', line) or re.search(r'\bessential\b', line, re.IGNORECASE):
                cleaned = re.sub(r'\s*\(E\)\s*$', '', line)
                cleaned = re.sub(r'^[-•*·▪◦➤]\s*', '', cleaned)
                cleaned = re.sub(r'^\d+[.)]\s*', '', cleaned)
                if cleaned and len(cleaned) > 5:
                    essential.append(cleaned.strip())

            elif re.search(r'\(D\)\s*$', line) or re.search(r'\bdesirable\b', line, re.IGNORECASE):
                cleaned = re.sub(r'\s*\(D\)\s*$', '', line)
                cleaned = re.sub(r'^[-•*·▪◦➤]\s*', '', cleaned)
                cleaned = re.sub(r'^\d+[.)]\s*', '', cleaned)
                if cleaned and len(cleaned) > 5:
                    desirable.append(cleaned.strip())

    # Strategy 3: Extract named sections (Qualifications, Experience, etc.)
    section_headers = [
        'qualifications', 'education', 'experience', 'skills',
        'knowledge', 'personal qualities', 'personal attributes',
        'other requirements', 'additional requirements',
        'main duties', 'key responsibilities', 'responsibilities',
    ]
    for header in section_headers:
        pattern = re.compile(
            rf'(?:^|\n)\s*(?:##?\s*)?{header}\s*[:\-]?\s*\n(.*?)(?=\n\s*(?:##?\s*)?(?:{"|".join(section_headers)}|essential|desirable|closing|salary|about|$))',
            re.IGNORECASE | re.DOTALL
        )
        match = pattern.search(text)
        if match:
            unparsed_sections[header.title()] = match.group(1).strip()

    return {
        'essential': essential,
        'desirable': desirable,
        'unparsed_sections': unparsed_sections,
    }


def extract_keywords(job_description):
    """
    Scan the job description for NHS-domain keywords and terms that
    should appear in the applicant's CV.

    Returns a dict of {category: [matched_terms]}
    """
    if not job_description:
        return {}

    text = job_description.lower()
    matches = OrderedDict()

    for category, terms in NHS_KEYWORDS.items():
        found = []
        for term in terms:
            # Use word boundary matching for short terms, substring for longer ones
            if len(term) <= 4:
                # Short terms like 'NMC', 'ALS' — need word boundaries
                # and case-insensitive match against original text
                if re.search(rf'\b{re.escape(term)}\b', job_description, re.IGNORECASE):
                    if term not in found:
                        found.append(term)
            else:
                if term.lower() in text:
                    if term not in found:
                        found.append(term)
        if found:
            matches[category] = found

    return matches


def generate_cv_checklist(job_description, job_title="", employer=""):
    """
    Generate a structured CV checklist from a job description.

    Returns a formatted string ready to display to the user.
    """
    if not job_description:
        return "No job description available to analyse."

    person_spec = extract_person_spec(job_description)
    keywords = extract_keywords(job_description)

    lines = []
    lines.append("=" * 60)
    lines.append("  CV CHECKLIST — Key things your resume should mention")
    lines.append("=" * 60)

    if job_title or employer:
        role_parts = []
        if job_title:
            role_parts.append(job_title)
        if employer:
            role_parts.append(f"at {employer}")
        lines.append(f"\n  Role: {' '.join(role_parts)}")

    # ── Person Specification ──
    if person_spec['essential'] or person_spec['desirable']:
        lines.append("\n" + "─" * 60)
        lines.append("PERSON SPECIFICATION")
        lines.append("─" * 60)
        lines.append("Assessors score your application against these criteria.")
        lines.append("Your CV must provide evidence for each essential item.\n")

        if person_spec['essential']:
            lines.append("ESSENTIAL (must address all of these):")
            for i, criterion in enumerate(person_spec['essential'], 1):
                lines.append(f"  [ ] {i}. {criterion}")

        if person_spec['desirable']:
            lines.append("\nDESIRABLE (address where you can — these differentiate candidates):")
            for i, criterion in enumerate(person_spec['desirable'], 1):
                lines.append(f"  [ ] {i}. {criterion}")

    # ── Keywords to include ──
    if keywords:
        lines.append("\n" + "─" * 60)
        lines.append("KEY TERMS TO INCLUDE IN YOUR CV")
        lines.append("─" * 60)
        lines.append("These specific terms appear in the job description.")
        lines.append("Mirror them in your CV where truthful — this helps")
        lines.append("with both human reviewers and keyword scanning.\n")

        category_labels = {
            'registrations': '📋 Registrations & Professional Bodies',
            'qualifications': '🎓 Qualifications & Certifications',
            'clinical_skills': '🏥 Clinical Skills & Competencies',
            'systems_and_frameworks': '💻 Systems & Frameworks',
            'soft_skills': '🤝 Skills & Competencies',
            'compliance_and_checks': '✅ Compliance & Pre-employment',
        }

        for category, terms in keywords.items():
            label = category_labels.get(category, category.replace('_', ' ').title())
            lines.append(f"  {label}:")
            lines.append(f"    {', '.join(terms)}")
            lines.append("")

    # ── Unparsed sections (duties, responsibilities) ──
    if person_spec['unparsed_sections']:
        lines.append("─" * 60)
        lines.append("KEY RESPONSIBILITIES MENTIONED")
        lines.append("─" * 60)
        lines.append("Your CV's work history should demonstrate experience")
        lines.append("with these duties where possible:\n")

        for section_name, content in person_spec['unparsed_sections'].items():
            bullets = _extract_bullet_points(content)
            if bullets:
                lines.append(f"  {section_name}:")
                for b in bullets[:8]:  # Cap at 8 to keep it readable
                    lines.append(f"    • {b}")
                if len(bullets) > 8:
                    lines.append(f"    ... and {len(bullets) - 8} more")
                lines.append("")

    # ── Summary advice ──
    if not person_spec['essential'] and not keywords:
        lines.append("\n" + "─" * 60)
        lines.append("Could not extract structured criteria from this listing.")
        lines.append("This may be a short advert. Read it carefully and ensure")
        lines.append("your CV covers the skills and experience mentioned.")
        lines.append("─" * 60)
    else:
        lines.append("─" * 60)
        lines.append("TIPS:")
        lines.append("  • Use the same language as the job description")
        lines.append("  • Quantify achievements where possible (numbers, %)")
        lines.append("  • Ensure your most recent role addresses the most criteria")
        lines.append("  • Don't claim what you can't evidence at interview")
        lines.append("─" * 60)

    return '\n'.join(lines)


def _extract_bullet_points(text):
    """
    Extract individual criteria/points from a block of text.
    Handles bullet points, numbered lists, and line-separated items.
    """
    if not text:
        return []

    points = []

    # Split on common bullet/list markers
    # Handles: - item, • item, * item, · item, 1. item, a) item, etc.
    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Remove leading bullet markers
        cleaned = re.sub(r'^[-•*·▪◦➤►→]\s*', '', line)
        cleaned = re.sub(r'^\d+[.)]\s*', '', cleaned)
        cleaned = re.sub(r'^[a-z][.)]\s*', '', cleaned)

        # Skip very short or header-like lines
        if len(cleaned) < 5:
            continue
        if cleaned.endswith(':') and len(cleaned) < 40:
            continue

        # Skip lines that are just section headers
        if cleaned.lower() in ('essential', 'desirable', 'essential criteria',
                                'desirable criteria', 'person specification'):
            continue

        points.append(cleaned.strip())

    return points