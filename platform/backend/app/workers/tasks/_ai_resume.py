"""AI-powered resume customization using Claude API."""

import logging
from app.config import get_settings

logger = logging.getLogger(__name__)


def customize_resume(
    resume_text: str,
    job_title: str,
    job_description: str,
    matched_keywords: list[str],
    missing_keywords: list[str],
    target_score: int = 85,
) -> dict:
    """Use Claude to customize a resume for a specific job posting.

    Returns dict with customized_text, changes_made, and improvement_notes.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return {
            "customized_text": "",
            "changes_made": [],
            "improvement_notes": "AI customization requires an Anthropic API key. Please configure ANTHROPIC_API_KEY.",
            "error": True,
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = f"""You are an expert ATS (Applicant Tracking System) resume optimizer.
Your task is to customize the provided resume to better match the target job posting.

TARGET ATS SCORE: {target_score}% match

JOB TITLE: {job_title}

JOB DESCRIPTION:
{job_description[:3000] if job_description else "Not available - optimize based on job title and keywords."}

KEYWORDS ALREADY MATCHED: {', '.join(matched_keywords[:20])}
KEYWORDS MISSING (must add): {', '.join(missing_keywords[:15])}

CURRENT RESUME:
{resume_text[:4000]}

INSTRUCTIONS:
1. Rewrite the resume to naturally incorporate the missing keywords where relevant
2. Keep the person's actual experience truthful - don't fabricate experience
3. Reorganize sections to highlight the most relevant experience first
4. Use industry-standard section headers (Experience, Skills, Education, Certifications)
5. Add quantifiable achievements where possible
6. Ensure ATS-friendly formatting (no tables, no graphics descriptions)
7. Target approximately {target_score}% keyword match with the job posting

Return your response in this exact format:

===CUSTOMIZED RESUME===
[The full customized resume text]

===CHANGES MADE===
- [List each specific change you made]

===IMPROVEMENT NOTES===
[Brief notes on what was improved and why, and any suggestions the candidate should verify/adjust]"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Parse response sections
        customized_text = ""
        changes_made = []
        improvement_notes = ""

        if "===CUSTOMIZED RESUME===" in response_text:
            parts = response_text.split("===CUSTOMIZED RESUME===")
            rest = parts[1] if len(parts) > 1 else ""

            if "===CHANGES MADE===" in rest:
                resume_part, rest2 = rest.split("===CHANGES MADE===", 1)
                customized_text = resume_part.strip()

                if "===IMPROVEMENT NOTES===" in rest2:
                    changes_part, notes_part = rest2.split("===IMPROVEMENT NOTES===", 1)
                    changes_made = [c.strip().lstrip("- ") for c in changes_part.strip().split("\n") if c.strip().startswith("-")]
                    improvement_notes = notes_part.strip()
                else:
                    changes_made = [c.strip().lstrip("- ") for c in rest2.strip().split("\n") if c.strip().startswith("-")]
            else:
                customized_text = rest.strip()
        else:
            customized_text = response_text

        return {
            "customized_text": customized_text,
            "changes_made": changes_made,
            "improvement_notes": improvement_notes,
            "error": False,
            "input_tokens": message.usage.input_tokens if hasattr(message, 'usage') else 0,
            "output_tokens": message.usage.output_tokens if hasattr(message, 'usage') else 0,
        }

    except Exception as e:
        logger.error("AI resume customization failed: %s", e)
        return {
            "customized_text": "",
            "changes_made": [],
            "improvement_notes": f"AI customization failed: {str(e)}",
            "error": True,
        }
