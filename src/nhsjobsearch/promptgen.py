"""
Prompt generator for NHS/DWP job applications.

Workflow:
  1. User selects a job from the index
  2. Tool extracts the full job description (via connector)
  3. User provides:
     - Application questions (copied from the form)
     - Optional additional experience notes
  4. Tool generates a well-structured LLM prompt that the user pastes
     into their LLM of choice (where their CV is already uploaded)

The generated prompt is designed so the LLM will:
  - Analyse the job description and person specification
  - Cross-reference against the user's CV (already in context)
  - Answer each application question with tailored, evidence-based responses
  - Use the STAR method where appropriate
  - Align with NHS values
"""

import textwrap
from datetime import datetime


def generate_prompt(job_description, questions, additional_context="", job_title="", employer="", word_limit=None):
    """
    Generate an optimised LLM prompt for answering NHS job application questions.

    Args:
        job_description: Full text of the job description / person specification
        questions: List of question strings the applicant needs to answer
        additional_context: Optional extra info the user wants the LLM to consider
            (e.g. specific projects, certifications, personal circumstances)
        job_title: Title of the role
        employer: Name of the employer / trust
        word_limit: Optional word limit per answer (some NHS forms enforce this)

    Returns:
        A string containing the complete prompt to paste into the LLM.
    """

    # --- Build the question block ---
    questions_block = ""
    q_num = 0
    for q in questions:
        q = q.strip()
        if q:
            q_num += 1
            questions_block += f"Question {q_num}: {q}\n"

    if not questions_block:
        questions_block = (
            "Question 1: Supporting statement — explain why you are suitable "
            "for this role and how you meet the person specification.\n"
        )

    # --- Word limit instruction ---
    word_limit_instruction = ""
    if word_limit:
        word_limit_instruction = (
            f"\n**Word limit**: Each answer must be under {word_limit} words. "
            f"Be concise and impactful — every sentence should earn its place.\n"
        )

    # --- Additional context block ---
    context_block = ""
    if additional_context.strip():
        context_block = f"""
<ADDITIONAL_CONTEXT>
The applicant has provided these additional notes about their experience,
circumstances, or points they want emphasised. Weave these in naturally
where they strengthen an answer — do not force them into every response.

{additional_context.strip()}
</ADDITIONAL_CONTEXT>
"""

    # --- Role identification ---
    role_line = ""
    if job_title or employer:
        parts = []
        if job_title:
            parts.append(job_title)
        if employer:
            parts.append(f"at {employer}")
        role_line = f"The role is: **{' '.join(parts)}**\n"

    # --- Assemble the prompt ---
    prompt = f"""\
You are an expert NHS job application consultant. Your task is to draft \
high-quality answers to the application questions below, based on the \
applicant's CV/resume (which you already have in this conversation) and \
the job description provided.

{role_line}
<JOB_DESCRIPTION>
{job_description.strip()}
</JOB_DESCRIPTION>
{context_block}
<APPLICATION_QUESTIONS>
{questions_block.strip()}
</APPLICATION_QUESTIONS>
{word_limit_instruction}
## Your approach

For each question, follow this process internally before writing:

1. **Extract requirements**: Identify the essential and desirable criteria \
from the job description and person specification that this question is \
assessing.

2. **Match to CV**: Find the strongest evidence from the applicant's CV \
that demonstrates each criterion. Prioritise recent, relevant, and \
measurable examples.

3. **Fill gaps**: Where the CV doesn't directly cover a criterion, look \
for transferable skills or adjacent experience that can be positioned \
convincingly. If additional context was provided, check whether it \
addresses any gaps.

4. **Draft using STAR-E**: Structure each example using:
   - **S**ituation — brief context (1 sentence)
   - **T**ask — what was required of you specifically
   - **A**ction — what you did (use "I" not "we")
   - **R**esult — measurable outcome or impact
   - **E**valuation — what you learned / would do differently (where space allows)

5. **Align with NHS values**: Where natural, demonstrate alignment with:
   - Working together for patients
   - Respect and dignity
   - Commitment to quality of care
   - Compassion
   - Improving lives
   - Everyone counts

## Output format

For each question, provide:

### Question [N]: [short title]

**Criteria being assessed**: [list the key criteria from the person spec]

**Draft answer**:
[The actual answer text the applicant would submit. Written in first person. \
Professional but warm tone. No headers or bullet points within the answer \
unless the form specifically uses them — NHS assessors expect flowing prose.]

**Assessor notes**: [Brief note on which essential/desirable criteria this \
answer covers, and any gaps the applicant should be aware of]

---

## Important rules

- Write in the **first person** as the applicant. Do not refer to "the \
candidate" — use "I".
- Only output the answers one question at a time, after the user has \
read the response and approved. Do not write all answers in one go.
- Be **specific and evidence-based**. Vague claims like "I am a team \
player" must be backed by a concrete example from the CV.
- **Do not fabricate** experience, qualifications, or events. Only use \
what is in the CV and the additional context provided. If there is a gap, \
flag it in the assessor notes rather than inventing evidence.
- Match the **tone** to the band/seniority of the role: clinical \
authority for senior roles, enthusiasm and willingness to learn for \
entry-level roles.
- Where the job description mentions specific systems, frameworks, or \
standards (e.g. NMC, CQC, safeguarding levels), reference them by name \
if the CV supports it.
- For supporting statements, address **every essential criterion** from \
the person specification. Desirable criteria should be covered where the \
CV provides evidence.
- Avoid generic NHS praise. Instead, reference specific aspects of the \
employer or service that connect to the applicant's experience.

Begin.
"""
    return textwrap.dedent(prompt)


def generate_prompt_interactive():
    """
    Interactive CLI flow for the prompt generator.
    Returns the generated prompt string, or None if cancelled.
    """
    print("\n" + "=" * 60)
    print("  NHS Job Application — Prompt Generator")
    print("=" * 60)

    print("\nThis tool generates an optimised prompt for your LLM.")
    print("Paste it into ChatGPT / Claude / etc. where your CV is uploaded.\n")

    # Job description
    print("─" * 40)
    print("Step 1: Job Description")
    print("─" * 40)
    print("Paste the full job description and person specification below.")
    print("When done, enter a blank line then type 'END' on a new line.\n")

    job_description = _multiline_input()
    if not job_description.strip():
        print("No job description provided. Aborting.")
        return None

    # Job title and employer (optional, for better prompting)
    print("\n─" * 40)
    print("Step 2: Role Details (optional, press Enter to skip)")
    print("─" * 40)
    job_title = input("Job title: ").strip()
    employer = input("Employer/Trust: ").strip()

    # Questions
    print("\n─" * 40)
    print("Step 3: Application Questions")
    print("─" * 40)
    print("Enter each question, one per line.")
    print("Press Enter twice when done.\n")
    print("If there are no specific questions, just press Enter and the")
    print("prompt will default to a general supporting statement.\n")

    questions = []
    empty_count = 0
    while True:
        q = input(f"  Q{len(questions) + 1}: ").strip()
        if not q:
            empty_count += 1
            if empty_count >= 1 and questions:
                break
            if empty_count >= 2:
                break
            continue
        empty_count = 0
        questions.append(q)

    # Additional context
    print("\n─" * 40)
    print("Step 4: Additional Context (optional)")
    print("─" * 40)
    print("Any extra experience, certifications, or points you want")
    print("emphasised that might not be on your CV?")
    print("Enter blank line then 'END' when done, or just 'END' to skip.\n")

    additional_context = _multiline_input()

    # Word limit
    print("\n─" * 40)
    print("Step 5: Word Limit")
    print("─" * 40)
    word_limit_str = input("Word limit per answer (press Enter for none): ").strip()
    word_limit = None
    if word_limit_str.isdigit():
        word_limit = int(word_limit_str)

    # Generate
    prompt = generate_prompt(
        job_description=job_description,
        questions=questions,
        additional_context=additional_context,
        job_title=job_title,
        employer=employer,
        word_limit=word_limit,
    )

    return prompt


def _multiline_input():
    """Read multiple lines until the user types END on its own line."""
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().upper() == 'END':
            break
        lines.append(line)
    return '\n'.join(lines)


def run_prompt_generator(job_description=None, job_title="", employer=""):
    """
    Main entry point. Can be called with a pre-fetched job description
    (e.g. from the display selecting a job) or will prompt for one.

    Returns the generated prompt, also copies to clipboard if possible.
    """

    if job_description:
        # Pre-populated flow (called from display or API)
        print("\n" + "=" * 60)
        print("  NHS Job Application — Prompt Generator")
        print("=" * 60)
        if job_title:
            print(f"\n  Role: {job_title}")
        if employer:
            print(f"  Employer: {employer}")
        print(f"\n  Job description loaded ({len(job_description.split())} words)")

        print("\n─" * 40)
        print("Application Questions")
        print("─" * 40)
        print("Enter each question, one per line. Press Enter twice when done.\n")

        questions = []
        empty_count = 0
        while True:
            q = input(f"  Q{len(questions) + 1}: ").strip()
            if not q:
                empty_count += 1
                if empty_count >= 1 and questions:
                    break
                if empty_count >= 2:
                    break
                continue
            empty_count = 0
            questions.append(q)

        print("\n─" * 40)
        print("Additional Context (optional)")
        print("─" * 40)
        print("Extra experience or points to emphasise?")
        print("Type 'END' on its own line when done, or just 'END' to skip.\n")
        additional_context = _multiline_input()

        word_limit_str = input("\nWord limit per answer (Enter for none): ").strip()
        word_limit = int(word_limit_str) if word_limit_str.isdigit() else None

        prompt = generate_prompt(
            job_description=job_description,
            questions=questions,
            additional_context=additional_context,
            job_title=job_title,
            employer=employer,
            word_limit=word_limit,
        )
    else:
        # Fully interactive flow
        prompt = generate_prompt_interactive()

    if not prompt:
        return None

    # Output the CV checklist first
    from .cvextract import generate_cv_checklist
    checklist = generate_cv_checklist(
        job_description if job_description else "",
        job_title=job_title,
        employer=employer,
    )
    print("\n" + checklist)

    # Output the prompt
    print("\n" + "=" * 60)
    print("  GENERATED PROMPT — Copy everything below this line")
    print("=" * 60 + "\n")
    print(prompt)
    print("\n" + "=" * 60)
    print("  END OF PROMPT — Copy everything above this line")
    print("=" * 60)

    # Try to copy to clipboard
    _try_clipboard(prompt)

    # Save to file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_title = "".join(c if c.isalnum() or c in ' -_' else '' for c in job_title)[:40].strip().replace(' ', '_')
    filename = f"prompt_{safe_title}_{timestamp}.txt" if safe_title else f"prompt_{timestamp}.txt"

    try:
        from . import config
        import os
        cache_dir = os.path.expanduser(config.CONFIG['CACHE']['path'])
        os.makedirs(os.path.join(cache_dir, 'prompts'), exist_ok=True)
        filepath = os.path.join(cache_dir, 'prompts', filename)
        with open(filepath, 'w') as f:
            f.write(prompt)
        print(f"\nPrompt saved to: {filepath}")
    except Exception:
        pass

    return prompt


def _try_clipboard(text):
    """Try to copy text to system clipboard. Silently fails if not available."""
    try:
        import subprocess
        # macOS
        proc = subprocess.run(['pbcopy'], input=text.encode(), check=True,
                              capture_output=True, timeout=2)
        print("\n✓ Prompt copied to clipboard!")
        return
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    try:
        import subprocess
        # Linux with xclip
        proc = subprocess.run(['xclip', '-selection', 'clipboard'],
                              input=text.encode(), check=True,
                              capture_output=True, timeout=2)
        print("\n✓ Prompt copied to clipboard!")
        return
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    print("\n(Clipboard not available — copy the prompt manually)")