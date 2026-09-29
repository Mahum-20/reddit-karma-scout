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
You are a seasoned backend software engineer (Python/Django/FastAPI) and quantitative/SMC trader commenting on Reddit.
Your objective is to build genuine community credibility and karma through insightful, constructive, peer-level participation.
Every comment you write must make someone who clicks your profile think: "This person is genuinely competent and knows their craft."

### COMMUNITY-SPECIFIC DIRECTIVES:
1. Programming & Backend (r/Python, r/django, r/learnprogramming, r/webdev):
   - Provide concrete, actionable technical solutions (e.g. resolving N+1 queries with select_related/prefetch_related, DB indexes, Celery task decoupling, clean architecture).
   - Sound like a pragmatic production developer. Answer the core question directly in sentence 1.
2. Trading & Quantitative Finance (r/algotrading, r/Forex, r/Daytrading, r/stocks):
   - Focus on market structure, SMC nuances (BOS/CHOCH validation, liquidity sweeps), backtesting curve-fitting, or risk management.
   - Strictly NO hype, NO signal-selling, NO get-rich-quick claims. Sound like a disciplined, analytical trader.
3. Career & Tech Industry (r/cscareerquestions, r/careerguidance):
   - Give grounded advice: prioritize end-to-end projects that solve real business problems over generic tutorial clones (like basic to-do apps).
4. General / Local Discussions (r/pakistan, r/AskReddit, r/CasualConversation):
   - Share a brief, grounded, authentic perspective or relatable observation.

### STRICT BANS (PREVENTING SPAM FLAGS):
- NEVER self-promote, drop links to GitHub/websites, or say "hire me", "check my profile", or "DM me".
- NEVER write lazy filler like "Great post!", "So true", "This!", "Agreed", "Good luck bro", or "lol".
- NO bullet points, NO bold headings, NO numbered lists, NO quotes around your text.
- NO robotic openings: Never say "Great question!", "Here is my advice:", or "As a software engineer...".

### FORMATTING & TONE:
- Length: Strictly 2 to 4 sentences. Fast to read, packed with real substance.
- Use natural developer cadence: casual, professional, conversational.
- Output ONLY the comment text itself. Nothing else.
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
        for fallback in ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]:
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
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        logger.warning(f"Gemini API 5 RPM rate limit reached. Backing off for 12 seconds...")
                        time.sleep(12)
                        continue
                    elif "503" in err_str or "UNAVAILABLE" in err_str:
                        logger.debug(f"Model {model_name} temporary 503 spike, retrying in 2s...")
                        time.sleep(2)
                        continue
                    elif "404" in err_str or "NOT_FOUND" in err_str:
                        logger.debug(f"Model {model_name} unavailable, moving to next model...")
                        break
                    else:
                        logger.error(f"Gemini API error generating draft ({model_name}): {e}")
                        break

        # If API is exhausted, return None rather than sending irrelevant off-topic canned text
        logger.warning(f"Could not generate custom comment for '{post_title[:40]}...'. Skipping to avoid irrelevant alerts.")
        return None

    def generate_original_post_idea(self, subreddit: str) -> Optional[dict]:
        """
        Generates a viral, high-karma original post concept tailored to a specific community.
        Returns a dict with {"title": ..., "body": ..., "strategy": ...}.
        """
        if not self.client:
            return None

        prompt = f"""
        Generate ONE high-engagement, viral original post concept for r/{subreddit}.
        The post must strictly adhere to the posting rules and subculture of r/{subreddit}.

        Community rules:
        - For r/AskReddit, r/Showerthoughts, r/NoStupidQuestions:
          * "title": A brilliant, open-ended thought or question that triggers immediate curiosity and hundreds of answers.
          * "body": Must be empty string "" because these communities forbid text in the post body (Rule 1).
        - For technical & finance communities (r/Python, r/django, r/algotrading, r/learnprogramming, r/cscareerquestions):
          * "title": A real-world architectural dilemma, optimization question, or relatable dev debate.
          * "body": 2-3 sentences providing realistic production context and asking peers for their practical take.
        - For discussion communities (r/CasualConversation, r/pakistan, r/memes):
          * "title": Relatable, intriguing observation or open topic.
          * "body": Short context or setup if appropriate, otherwise "".

        Requirements:
        1. "title": Authentic, conversational, attention-grabbing (NO AI buzzwords, NO clickbait).
        2. "body": Context if allowed by the subreddit, otherwise empty string "".
        3. "strategy": 1 concise sentence explaining why this angle drives massive upvotes and replies.

        Output strictly valid JSON with keys: "title", "body", "strategy".
        """.strip()

        import json
        import time

        candidate_models = [self.config.gemini_model]
        for fallback in ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        for model_name in candidate_models:
            for attempt in range(2):
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.9,
                            max_output_tokens=600,
                        ),
                    )
                    if response and response.text:
                        data = json.loads(response.text.strip())
                        if "title" in data and "body" in data:
                            return data
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        time.sleep(10)
                        continue
                    elif "503" in err_str or "UNAVAILABLE" in err_str:
                        time.sleep(2)
                        continue
                    break

        return None
