"""
AI Draft Generation module using Google's google-genai SDK.
Crafts high-upvote Reddit comments tailored to community psychology,
rising thread timing, and the 5 proven Reddit karma archetypes.
"""
import logging
from typing import Optional
from google import genai
from google.genai import types

from config import Config

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
You are an elite Reddit commenter known for consistently getting top-voted comments on rising threads.
Your goal is to write a comment that naturally gathers hundreds of upvotes based on Reddit psychology and community culture.

### THE 5 HIGH-UPVOTE ARCHETYPES (Pick the BEST one for the post):
1. THE HYPER-RELATABLE TAKE (Best for general/casual subs):
   - A specific, funny, or slightly embarrassing shared human habit that makes people think: "I thought I was the only one who did that!"
2. THE QUICK HUMOR / SHARP ROAST (Best for memes, funny, or quirky questions):
   - Short, punchy, unexpected deadpan humor or witty observation.
3. THE DIRECT & INSIGHTFUL ANSWER (Best for Q&A, advice, or explain subs):
   - Put the core answer/solution right in the very first sentence. Zero filler backstory.
4. THE COUNTERINTUITIVE POINT (The Clever Hot Take):
   - Respectfully flips the common assumption or perspective on its head with a clever angle.
5. THE VIVID MICRO-ANECDOTE:
   - A brief, specific 1-2 sentence real-life experience or observation that rings instantly authentic.

### STRICT BANS (WHAT KILLS UPVOTES):
- NEVER write lazy filler like "this is relatable", "lowkey relatable tbh", "so true", "this!", "couldn't agree more", "ngl that's wild", or "lol". Every single comment must contain a concrete thought, specific detail, or joke.
- NO options or lists: NEVER provide multiple variations, options (e.g. "Option A", "Option 1"), or alternatives. Pick the single best comment and write only that.
- NO AI formatting: NO bullet points, NO bold headings, NO numbered lists, NO quotes around your response.
- NO robotic openings: Never say "Great question!", "Here is my take:", "I think that...", or "As someone who...".
- NO emoji spam: Use at most one natural emoji if fitting, but zero is usually better on Reddit.
- NO mentions of karma, upvotes, or algorithms.

### FORMATTING & TONE:
- Length: Strictly 1 to 3 sentences maximum. Fast to read, fast to upvote.
- Use a natural, organic conversational tone (like a real person typing casually on their phone).
- If writing 2-3 sentences, use a clean line break between thoughts.
- Output ONLY the raw comment text. Nothing else.
""".strip()


class AIDrafter:
    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[genai.Client] = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.config.gemini_api_key:
            logger.warning("No GEMINI_API_KEY provided. AI draft generation will be disabled.")
            return

        try:
            self.client = genai.Client(api_key=self.config.gemini_api_key)
            logger.info("Gemini Client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini Client: {e}")
            self.client = None

    def draft_comment(self, subreddit: str, post_title: str, selftext: str = "") -> Optional[str]:
        """
        Generates a 1-3 sentence high-converting comment draft tailored to the post and subreddit.
        """
        if not self.client:
            return "DoorDash. You'll happily pay $38 for a lukewarm $12 burrito just to avoid putting on pants."

        # Prompt providing post context and subreddit culture
        prompt = f"Target Community: r/{subreddit}\nPost Title: {post_title}"
        if selftext.strip():
            snippet = selftext.strip()[:400]
            prompt += f"\nPost Body:\n{snippet}"

        prompt += "\n\nDraft the single best high-upvote comment following your instructions. Output ONLY the comment."

        import time
        # Candidate models to try in order
        candidate_models = [self.config.gemini_model]
        for fallback in ["gemini-flash-latest", "gemini-3.8-flash", "gemini-2.5-flash"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        for model_name in candidate_models:
            for attempt in range(2):
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.85,
                            max_output_tokens=1000,
                        ),
                    )
                    if response and response.text:
                        clean_draft = response.text.strip().strip('"').strip("'")
                        lines = [ln.strip() for ln in clean_draft.split("\n") if ln.strip()]
                        filtered_lines = []
                        for line in lines:
                            if line.startswith(("* Option", "Option ", "1.", "2.", "3.", "Style ", "###", "- ")):
                                break
                            filtered_lines.append(line)
                        if filtered_lines:
                            clean_draft = "\n\n".join(filtered_lines[:3])
                        return clean_draft
                except Exception as e:
                    err_str = str(e)
                    if "503" in err_str or "UNAVAILABLE" in err_str:
                        logger.debug(f"Model {model_name} temporary 503 spike, retrying in 1.5s...")
                        time.sleep(1.5)
                        continue
                    elif "404" in err_str or "NOT_FOUND" in err_str:
                        logger.debug(f"Model {model_name} unavailable, moving to next model...")
                        break
                    else:
                        logger.error(f"Gemini API error generating draft ({model_name}): {e}")
                        break

        # High-effort concrete fallback examples if API network disconnects
        import random
        fallbacks = [
            "the worst feeling is typing out a paragraph, looking at it, and deleting the whole thing because you realize you just don't care enough.",
            "buying a whole bunch of fresh groceries with grand cooking plans, only to stare into the fridge and order takeout three hours later.",
            "setting four different alarms five minutes apart because you know past-you cannot be trusted under any circumstances.",
        ]
        return random.choice(fallbacks)
