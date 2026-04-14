"""AI-powered cover letter generation using Claude API."""

import logging
from app.config import get_settings

logger = logging.getLogger(__name__)


def generate_cover_letter(
    resume_text: str,
    job_title: str,
    company_name: str,
    job_description: str,
    tone: str = "professional",
) -> dict:
    """Generate a tailored cover letter using Claude.

    Returns dict with cover_letter, key_points, and customization_notes.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return {
            "cover_letter": "",
            "key_points": [],
            "customization_notes": "AI cover letter generation requires an Anthropic API key.",
            "error": True,
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        tone_instructions = {
            "professional": "Use a polished, confident, professional tone. Be concise and results-oriented.",
            "enthusiastic": "Show genuine excitement about the role and company. Be warm but not over-the-top.",
            "technical": "Lead with technical expertise. Emphasize specific tools, frameworks, and measurable outcomes.",
            "conversational": "Use a friendly, approachable tone while still being professional. Show personality.",
        }

        prompt = f"""You are an expert career coach who writes compelling, personalized cover letters that get interviews.

CANDIDATE RESUME:
{resume_text[:3000]}

TARGET JOB:
Title: {job_title}
Company: {company_name}

JOB DESCRIPTION:
{job_description[:3000] if job_description else "Not available — write based on the job title and company."}

TONE: {tone_instructions.get(tone, tone_instructions["professional"])}

INSTRUCTIONS:
1. Write a cover letter (250-350 words) tailored specifically to this job
2. Open with a compelling hook — NOT "I am writing to apply for..."
3. Connect the candidate's specific experience to what the job requires
4. Show knowledge of the company and why this role is a fit
5. Include 2-3 concrete achievements or metrics from the resume
6. Close with a confident call to action
7. Do NOT fabricate experience — only reference what's in the resume
8. Do NOT use generic filler phrases

Return your response in this exact format:

===COVER LETTER===
[The full cover letter text]

===KEY POINTS===
- [Key selling point 1 that makes this candidate stand out for this specific role]
- [Key selling point 2]
- [Key selling point 3]

===NOTES===
[Brief notes on customization choices and what to adjust before sending]"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Parse sections
        cover_letter = ""
        key_points = []
        notes = ""

        if "===COVER LETTER===" in response_text:
            parts = response_text.split("===COVER LETTER===", 1)
            rest = parts[1] if len(parts) > 1 else ""

            if "===KEY POINTS===" in rest:
                letter_part, rest2 = rest.split("===KEY POINTS===", 1)
                cover_letter = letter_part.strip()

                if "===NOTES===" in rest2:
                    points_part, notes_part = rest2.split("===NOTES===", 1)
                    key_points = [p.strip().lstrip("- ") for p in points_part.strip().split("\n") if p.strip().startswith("-")]
                    notes = notes_part.strip()
                else:
                    key_points = [p.strip().lstrip("- ") for p in rest2.strip().split("\n") if p.strip().startswith("-")]
            else:
                cover_letter = rest.strip()
        else:
            cover_letter = response_text

        return {
            "cover_letter": cover_letter,
            "key_points": key_points,
            "customization_notes": notes,
            "tone": tone,
            "error": False,
        }

    except Exception as e:
        logger.error("Cover letter generation failed: %s", e)
        return {
            "cover_letter": "",
            "key_points": [],
            "customization_notes": f"Generation failed: {str(e)}",
            "error": True,
        }
