"""
Test the CV checklist extractor.
Run from project root with: python -m tests.testcvextract
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nhsjobsearch.cvextract import extract_person_spec, extract_keywords, generate_cv_checklist


SAMPLE_JD_STRUCTURED = """
Job Title: Band 5 Staff Nurse - Cardiology Ward
Employer: Norfolk & Suffolk Foundation NHS Trust

Main duties of the job:
- Deliver high quality, evidence-based nursing care to cardiology patients
- Assess, plan, implement and evaluate patient care
- Administer medications safely in line with NMC standards
- Work as part of the multidisciplinary team
- Supervise and mentor healthcare assistants and student nurses
- Maintain accurate patient records using SystmOne

Person Specification:

Essential:
- Registered Nurse (Adult) with active NMC registration
- Evidence of continuing professional development
- Minimum 12 months experience in acute care setting
- Excellent communication and interpersonal skills
- Ability to work effectively as part of a team
- Competent in IV cannulation and venepuncture
- Knowledge of cardiac monitoring and ECG interpretation
- Enhanced DBS clearance required

Desirable:
- Post-registration experience in cardiology or cardiac care
- Mentorship qualification (ENB 998 or equivalent)
- Experience with electronic patient record systems
- ALS certification
- Experience of clinical audit

Closing date: 15 January 2026
Salary: £29,970 to £36,483 per annum
"""

SAMPLE_JD_INLINE_MARKERS = """
Band 6 Physiotherapist

Requirements:
- HCPC registration (E)
- Degree in Physiotherapy (E)
- 2 years post-qualification experience (E)
- Experience in musculoskeletal outpatients (E)
- Manual therapy skills (E)
- PRINCE2 certification (D)
- Leadership experience (D)
- Research or audit experience (D)
"""

SAMPLE_JD_MINIMAL = """
Healthcare Assistant - Care Home

We're looking for a caring, compassionate person to join our team.
You'll help residents with daily living activities, personal care,
and meal times. Must be flexible to work shifts including weekends.

No experience necessary - full training provided.
Must have right to work in the UK.
Enhanced DBS check required.
"""


def test_person_spec_structured():
    print("=== Testing Person Spec Extraction (structured) ===")
    result = extract_person_spec(SAMPLE_JD_STRUCTURED)

    assert len(result['essential']) > 0, "Should find essential criteria"
    assert len(result['desirable']) > 0, "Should find desirable criteria"

    print(f"  Essential: {len(result['essential'])} criteria")
    for c in result['essential']:
        print(f"    - {c}")

    print(f"  Desirable: {len(result['desirable'])} criteria")
    for c in result['desirable']:
        print(f"    - {c}")

    # Check specific criteria are found
    essential_text = ' '.join(result['essential']).lower()
    assert 'nmc' in essential_text or 'registered nurse' in essential_text, \
        "Should find NMC registration in essential"
    assert 'cannulation' in essential_text or 'venepuncture' in essential_text, \
        "Should find clinical skills in essential"

    desirable_text = ' '.join(result['desirable']).lower()
    assert 'als' in desirable_text or 'cardiology' in desirable_text, \
        "Should find ALS or cardiology in desirable"

    print("  ✓ Structured person spec OK\n")


def test_person_spec_inline():
    print("=== Testing Person Spec Extraction (inline markers) ===")
    result = extract_person_spec(SAMPLE_JD_INLINE_MARKERS)

    assert len(result['essential']) > 0, "Should find (E) marked items"
    assert len(result['desirable']) > 0, "Should find (D) marked items"

    print(f"  Essential: {len(result['essential'])} criteria")
    for c in result['essential']:
        print(f"    - {c}")

    print(f"  Desirable: {len(result['desirable'])} criteria")
    for c in result['desirable']:
        print(f"    - {c}")

    print("  ✓ Inline markers OK\n")


def test_keyword_extraction():
    print("=== Testing Keyword Extraction ===")
    keywords = extract_keywords(SAMPLE_JD_STRUCTURED)

    assert len(keywords) > 0, "Should find some keywords"

    print(f"  Found {sum(len(v) for v in keywords.values())} keywords in {len(keywords)} categories:")
    for category, terms in keywords.items():
        print(f"    {category}: {', '.join(terms)}")

    # Check specific expected keywords
    all_terms = [t.lower() for terms in keywords.values() for t in terms]
    assert any('nmc' in t for t in all_terms), "Should find NMC"
    assert any('cannulation' in t for t in all_terms), "Should find cannulation"
    assert any('ecg' in t for t in all_terms), "Should find ECG"
    assert any('dbs' in t.lower() for t in all_terms), "Should find DBS"
    assert any('systmone' in t.lower() for t in all_terms), "Should find SystmOne"

    print("  ✓ Keyword extraction OK\n")


def test_keyword_minimal():
    print("=== Testing Keywords on Minimal JD ===")
    keywords = extract_keywords(SAMPLE_JD_MINIMAL)

    print(f"  Found {sum(len(v) for v in keywords.values())} keywords:")
    for category, terms in keywords.items():
        print(f"    {category}: {', '.join(terms)}")

    all_terms = [t.lower() for terms in keywords.values() for t in terms]
    assert any('dbs' in t.lower() for t in all_terms), "Should find DBS even in minimal JD"

    print("  ✓ Minimal JD keywords OK\n")


def test_full_checklist():
    print("=== Testing Full CV Checklist Output ===")
    checklist = generate_cv_checklist(
        SAMPLE_JD_STRUCTURED,
        job_title="Band 5 Staff Nurse - Cardiology",
        employer="Norfolk & Suffolk Foundation NHS Trust",
    )

    assert len(checklist) > 200, f"Checklist too short: {len(checklist)}"
    assert 'ESSENTIAL' in checklist
    assert 'DESIRABLE' in checklist
    assert 'KEY TERMS' in checklist
    assert '[ ]' in checklist  # Checkbox format
    assert 'NMC' in checklist
    assert 'TIPS' in checklist

    print(checklist)
    print("\n  ✓ Full checklist OK\n")


def test_empty_jd():
    print("=== Testing Empty JD Handling ===")

    result = extract_person_spec("")
    assert result['essential'] == []
    assert result['desirable'] == []

    keywords = extract_keywords("")
    assert keywords == {}

    checklist = generate_cv_checklist("")
    assert 'No job description' in checklist

    print("  ✓ Empty JD handled OK\n")


if __name__ == '__main__':
    test_person_spec_structured()
    test_person_spec_inline()
    test_keyword_extraction()
    test_keyword_minimal()
    test_full_checklist()
    test_empty_jd()
    print("All CV extractor tests passed! ✓")