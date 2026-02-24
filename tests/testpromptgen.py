"""
Test the prompt generator output.
Run from project root with: python -m tests.testpromptgen
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nhsjobsearch.promptgen import generate_prompt


SAMPLE_JOB_DESCRIPTION = """
Job Title: Band 5 Staff Nurse - Cardiology Ward
Employer: Norfolk & Suffolk Foundation NHS Trust

Main duties of the job:
- Deliver high quality, evidence-based nursing care to cardiology patients
- Assess, plan, implement and evaluate patient care
- Administer medications safely in line with NMC standards
- Work as part of the multidisciplinary team
- Supervise and mentor healthcare assistants and student nurses
- Maintain accurate patient records using electronic systems

Person Specification:

Essential:
- Registered Nurse (Adult) with active NMC registration
- Evidence of continuing professional development
- Experience in acute care setting
- Excellent communication and interpersonal skills
- Ability to work effectively as part of a team
- Competent in IV cannulation and venepuncture
- Knowledge of cardiac monitoring and ECG interpretation

Desirable:
- Post-registration experience in cardiology or cardiac care
- Mentorship qualification (ENB 998 or equivalent)
- Experience with electronic patient record systems
- ALS certification

We are committed to the NHS values of working together for patients,
respect and dignity, and commitment to quality of care.

Closing date: 15 January 2026
Salary: £29,970 to £36,483 per annum
"""

SAMPLE_QUESTIONS = [
    "Please provide a supporting statement explaining why you are suitable for this role and how you meet the person specification.",
    "Describe a time when you had to deal with a deteriorating patient. What did you do and what was the outcome?",
    "How do you demonstrate the NHS values in your day-to-day practice?",
]


def test_basic_generation():
    print("=== Testing Basic Prompt Generation ===")

    prompt = generate_prompt(
        job_description=SAMPLE_JOB_DESCRIPTION,
        questions=SAMPLE_QUESTIONS,
        job_title="Band 5 Staff Nurse - Cardiology Ward",
        employer="Norfolk & Suffolk Foundation NHS Trust",
    )

    assert prompt is not None
    assert len(prompt) > 500, f"Prompt too short: {len(prompt)} chars"
    print(f"  Generated prompt: {len(prompt)} chars, {len(prompt.split())} words")

    # Check key structural elements are present
    assert '<JOB_DESCRIPTION>' in prompt
    assert 'Cardiology' in prompt
    assert '<APPLICATION_QUESTIONS>' in prompt
    assert 'Question 1' in prompt
    assert 'Question 2' in prompt
    assert 'Question 3' in prompt
    assert 'STAR' in prompt
    assert 'NHS values' in prompt
    assert 'first person' in prompt.lower()
    assert 'Do not fabricate' in prompt
    print("  Structure checks: ✓")

    # Check all three questions appear
    assert 'supporting statement' in prompt.lower()
    assert 'deteriorating patient' in prompt.lower()
    print("  Questions included: ✓")

    print("  ✓ Basic generation OK\n")


def test_with_additional_context():
    print("=== Testing With Additional Context ===")

    prompt = generate_prompt(
        job_description=SAMPLE_JOB_DESCRIPTION,
        questions=SAMPLE_QUESTIONS,
        additional_context="I recently completed an ALS course in November 2025. "
                          "I also led a QI project on reducing cardiac arrest "
                          "response times on my current ward.",
        job_title="Band 5 Staff Nurse",
        employer="Norfolk & Suffolk Foundation NHS Trust",
    )

    assert '<ADDITIONAL_CONTEXT>' in prompt
    assert 'ALS course' in prompt
    assert 'QI project' in prompt
    print("  Additional context included: ✓")

    print("  ✓ Additional context OK\n")


def test_with_word_limit():
    print("=== Testing With Word Limit ===")

    prompt = generate_prompt(
        job_description=SAMPLE_JOB_DESCRIPTION,
        questions=["Supporting statement"],
        word_limit=500,
    )

    assert '500 words' in prompt
    assert 'concise' in prompt.lower()
    print("  Word limit instruction included: ✓")

    print("  ✓ Word limit OK\n")


def test_no_questions_defaults():
    print("=== Testing Default Question ===")

    prompt = generate_prompt(
        job_description=SAMPLE_JOB_DESCRIPTION,
        questions=[],
    )

    assert 'supporting statement' in prompt.lower()
    assert 'person specification' in prompt.lower()
    print("  Default question generated: ✓")

    print("  ✓ Default question OK\n")


def test_empty_questions_filtered():
    print("=== Testing Empty Questions Filtered ===")

    prompt = generate_prompt(
        job_description=SAMPLE_JOB_DESCRIPTION,
        questions=["Real question", "", "  ", "Another real question"],
    )

    assert 'Question 1: Real question' in prompt
    assert 'Question 2: Another real question' in prompt
    # Empty strings should not produce Question entries
    assert 'Question 3' not in prompt
    print("  Empty questions filtered out: ✓")

    print("  ✓ Empty filtering OK\n")


def test_prompt_quality_checklist():
    print("=== Testing Prompt Quality Checklist ===")

    prompt = generate_prompt(
        job_description=SAMPLE_JOB_DESCRIPTION,
        questions=SAMPLE_QUESTIONS,
        additional_context="Some extra context",
        job_title="Staff Nurse",
        employer="Norfolk Trust",
        word_limit=750,
    )

    checks = {
        "Role identification": "Staff Nurse" in prompt,
        "Employer named": "Norfolk Trust" in prompt,
        "JD in XML tags": "<JOB_DESCRIPTION>" in prompt and "</JOB_DESCRIPTION>" in prompt,
        "Questions in XML tags": "<APPLICATION_QUESTIONS>" in prompt,
        "Context in XML tags": "<ADDITIONAL_CONTEXT>" in prompt,
        "STAR method": "STAR" in prompt,
        "NHS values listed": "Working together for patients" in prompt,
        "First person instruction": "first person" in prompt.lower(),
        "Anti-fabrication rule": "fabricat" in prompt.lower(),
        "Evidence-based instruction": "evidence" in prompt.lower(),
        "Assessor notes requested": "Assessor notes" in prompt,
        "Criteria extraction step": "Extract requirements" in prompt,
        "CV matching step": "Match to CV" in prompt,
        "Word limit enforced": "750" in prompt,
        "Output format specified": "Draft answer" in prompt,
    }

    all_pass = True
    for name, passed in checks.items():
        status = "✓" if passed else "✗ FAIL"
        if not passed:
            all_pass = False
        print(f"  {status} {name}")

    assert all_pass, "Some quality checks failed"
    print("\n  ✓ All quality checks passed\n")


if __name__ == '__main__':
    test_basic_generation()
    test_with_additional_context()
    test_with_word_limit()
    test_no_questions_defaults()
    test_empty_questions_filtered()
    test_prompt_quality_checklist()
    print("All prompt generator tests passed! ✓")