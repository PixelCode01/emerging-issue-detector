import os
import logging
from google import genai

logger = logging.getLogger(__name__)

def generate_pm_insight(sample_tickets: list[str]) -> str:
    """
    Generates a single-sentence product manager insight from sample tickets
    using Gemini, with cascading model fallbacks.
    """
    fallback_text = f"Needs Review: {sample_tickets[0][:80]}..." if sample_tickets else "Needs Review: No tickets provided."
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY environment variable not found. Falling back to raw string.")
        return fallback_text

    client = genai.Client(api_key=api_key)
    
    models = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-pro"]
    
    prompt = (
        "Generate a single-sentence product manager insight from the following support tickets. "
        "Strictly output only the final insight sentence, with no conversational filler, markdown formatting, or prefixes.\n\n"
        "Tickets:\n" + "\n".join(f"- {t}" for t in sample_tickets)
    )

    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response.text:
                return response.text.strip()
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}. Trying next model...")
            
    logger.error("All Gemini models failed. Falling back to raw string.")
    return fallback_text
