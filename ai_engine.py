import os
import json
import logging
from typing import Optional, List, Dict, Any
from PIL import Image
import io
import re
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ai_engine")
logging.basicConfig(level=logging.INFO)

AI_ACCESS_DENIED_MESSAGE = "AI access denied. Contact admin."


class InterviewAIEngine:
    """
    Dual-Provider Intelligent Reasoning Engine powered by Groq & Google Gemini.
    Features:
    - Ultra-fast sub-second responses via Groq (gpt-oss-120b, qwen3.8-27b).
    - High-accuracy ~200ms audio transcription via Groq Whisper (whisper-large-v3-turbo).
    - Multimodal vision via Google Gemini (gemini-3.5-flash-lite) for LeetCode screen snips.
    - Automatic Failover: If Groq hits 30 RPM or quota limit (429), it instantly switches
      to Gemini without interrupting the live interview!
    """

    def __init__(self, gemini_key: Optional[str] = None, groq_key: Optional[str] = None):
        self.api_key = gemini_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.groq_api_key = groq_key or os.getenv("GROQ_API_KEY", "").strip()
        
        self.client = None          # Google Gemini Client
        self.groq_client = None     # Groq Client

        # Models
        self.gemini_primary_model = "gemini-3.5-flash-lite"
        self.gemini_fallback_models = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite"]
        self.groq_models = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]

        self.resume_text = ""
        self.job_description = ""
        self.candidate_name = ""
        self.candidate_email = ""
        self.candidate_phone = ""
        self.custom_instructions = ""
        self.google_search_enabled = False
        self.preferred_language = os.getenv("DEFAULT_CODING_LANG", "python")
        self.conversation_history: List[Dict[str, str]] = []
        try:
            self.max_history_turns = int(os.getenv("MAX_HISTORY_TURNS", "5"))
        except ValueError:
            self.max_history_turns = 5

        self.initialize_gemini()
        self.initialize_groq()

    def add_turn(self, role: str, content: str):
        """Append turn to rolling history; keep only the last max_history_turns * 2 messages."""
        self.conversation_history.append({"role": role, "content": content})
        max_msgs = self.max_history_turns * 2
        if len(self.conversation_history) > max_msgs:
            self.conversation_history = self.conversation_history[-max_msgs:]

    def clear_history(self):
        """Reset conversation memory."""
        self.conversation_history.clear()
        logger.info("Conversation history cleared.")

    def update_api_key(self, api_key: str):
        """Update Gemini API key."""
        self.api_key = api_key.strip()
        self.initialize_gemini()

    def update_groq_key(self, groq_key: str):
        """Update Groq API key."""
        self.groq_api_key = groq_key.strip()
        self.initialize_groq()

    def update_profile(
        self,
        resume: Optional[str] = None,
        jd: Optional[str] = None,
        preferred_language: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        candidate_name: Optional[str] = None,
        candidate_email: Optional[str] = None,
        candidate_phone: Optional[str] = None,
    ):
        """Update candidate context. Empty string clears fields."""
        if resume is not None:
            self.resume_text = resume.strip()
        if jd is not None:
            self.job_description = jd.strip()
        if preferred_language is not None and preferred_language.strip():
            self.preferred_language = preferred_language.strip().lower()
        if custom_instructions is not None:
            self.custom_instructions = custom_instructions.strip()[:4000]
        if candidate_name is not None:
            self.candidate_name = candidate_name.strip()
        if candidate_email is not None:
            self.candidate_email = candidate_email.strip()
        if candidate_phone is not None:
            self.candidate_phone = candidate_phone.strip()

    def initialize_gemini(self):
        """Initialize Google GenAI client."""
        if not self.api_key:
            logger.info("No Gemini API key provided.")
            self.client = None
            return

        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key, http_options={"timeout": 30000})
            logger.info("Google GenAI client initialized with 30s timeout.")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None

    @staticmethod
    def sanitize_error(raw_error: str, context: str = "Analysis") -> str:
        """
        Convert technical AI exception traces, status codes, and JSON dumps into
        clean, user-friendly messages without technical jargon or brand leaks.
        """
        err_str = str(raw_error or "").strip()
        if not err_str:
            return f"{context} failed. Please try again."

        lower_err = err_str.lower()

        # 1. 504 / DEADLINE_EXCEEDED / Timeout
        if "504" in err_str or "deadline_exceeded" in lower_err or "timed out" in lower_err or "timeout" in lower_err:
            return "Analysis timed out. The AI model took too long to process the screen. Please try again or snip a specific question region."

        # 2. 429 / RESOURCE_EXHAUSTED / Quota
        if "429" in err_str or "resource_exhausted" in lower_err or "quota" in lower_err:
            return "Quota exceeded. Please wait a few moments before trying again."

        # 3. 503 / UNAVAILABLE / Overloaded
        if "503" in err_str or "unavailable" in lower_err or "overloaded" in lower_err:
            return "AI service is temporarily overloaded. Please retry in a few seconds."

        # 4. 401 / 403 / API_KEY_INVALID / PERMISSION_DENIED
        if (
            "api_key_invalid" in lower_err
            or "permission_denied" in lower_err
            or "api key not valid" in lower_err
            or "401" in err_str
            or "403" in err_str
            or "unauthorized" in lower_err
        ):
            return "API key is invalid or unauthorized. Please connect admin."

        # 5. Connection / Network errors
        if any(term in lower_err for term in ["connecterror", "getaddrinfo", "connection refused", "network unreachable", "failed to connect"]):
            return "Unable to connect to Copilot. Please check your internet connection."

        # 6. JSON dictionary stripping fallback: extract 'message' if present
        json_msg_match = re.search(r"['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]", err_str)
        if json_msg_match:
            clean_msg = json_msg_match.group(1).strip()
            clean_msg = re.sub(r"\b(Google\s*Gemini|Gemini|Groq)\b", "AI", clean_msg, flags=re.IGNORECASE)
            return clean_msg

        # Remove raw dict structures like {...} or stack traces
        cleaned = re.sub(r"\{.*?\}", "", err_str).strip()
        cleaned = re.sub(r"\b(Google\s*Gemini|Gemini|Groq)\b", "AI", cleaned, flags=re.IGNORECASE).strip()
        cleaned = cleaned.rstrip(":.- ")
        if cleaned:
            return f"{cleaned}."

        return f"{context} failed. Please try again."

    def initialize_groq(self):
        """Initialize Groq client."""
        if not self.groq_api_key:
            logger.info("No Groq API key provided.")
            self.groq_client = None
            return

        try:
            import groq
            self.groq_client = groq.Groq(api_key=self.groq_api_key, timeout=10.0)
            logger.info("Groq client initialized successfully (LPU ultra-fast engine).")
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            self.groq_client = None

    @staticmethod
    def is_small_talk_or_greeting(text: str) -> bool:
        """
        Detects pure pleasantries, greetings, mic checks, and conversational acknowledgements.
        Returns True if the text should be dropped without calling LLM, saving tokens.
        Guarantees that ANY question touching technical, QA, or testing concepts is answered.
        """
        cleaned = text.strip().lower()
        cleaned = re.sub(r'^[^\w]+|[^\w]+$', '', cleaned)
        if not cleaned:
            return True

        # 1. Audio / Visual checks, mic checks, and volume testing (ALWAYS filter these)
        audio_check_patterns = [
            r"^(can\s+you\s+(hear|see)\s+me.*)$",
            r"^(am\s+i\s+(audible|visible).*)$",
            r"^(hello\s+can\s+you\s+(hear|see)\s+me.*)$",
            r"^(hi\s+can\s+you\s+(hear|see)\s+me.*)$",
            r"^(can\s+you\s+see\s+my\s+screen.*)$",
            r"^(is\s+my\s+screen\s+visible.*)$",
            r"^(audio|mic|sound|screen)\s+check$",
            r"^(testing(\s+(1\s*2\s*3|one\s+two\s+three))?)$",
            r"^((mic|audio)\s+testing)$",
            r"^(you\s+are\s+audible|you\s+are\s+visible|i\s+can\s+hear\s+you)$"
        ]
        for pat in audio_check_patterns:
            if re.match(pat, cleaned, re.IGNORECASE):
                return True

        # 2. Technical / QA Keyword Shield: If ANY domain keyword is present, NEVER treat as small talk
        qa_tech_whitelist = [
            "severity", "priority", "defect", "bug", "software testing", "test case", "test plan", "test suite",
            "smoke testing", "sanity testing", "regression", "retest", "exploratory", "uat",
            "selenium", "playwright", "cypress", "testng", "junit", "cucumber", "bdd",
            "api", "postman", "rest", "endpoint", "status code", "payload", "json",
            "sql", "query", "database", "table", "join", "index", "schema",
            "agile", "scrum", "sprint", "jira", "user story", "acceptance criteria",
            "locator", "xpath", "css selector", "assertion", "wait", "implicit", "explicit",
            "framework", "pom", "page object", "ci/cd", "pipeline", "jenkins", "git",
            "boundary", "equivalence", "decision table", "state transition",
            "performance", "jmeter", "load", "stress", "end to end", "e2e",
            "java", "python", "javascript", "typescript", "c#", "automation",
            "algorithm", "function", "class", "method", "variable", "interface",
            "difference", "lifecycle", "life cycle", "matrix"
        ]
        if any(kw in cleaned for kw in qa_tech_whitelist):
            return False

        # 3. Substantive inquiry markers: If question verbs exist, it is a substantive question
        question_indicators = [
            "what", "how", "why", "when", "where", "which", "explain",
            "describe", "define", "difference", "compare", "differentiate",
            "implement", "design", "solve", "write", "tell me", "walk me",
            "could you", "would you", "can you explain", "can you tell", "can you define",
            "give an example", "complexity", "approach", "architecture", "pattern", "experience with"
        ]
        if any(q in cleaned for q in question_indicators):
            return False

        # 4. Pure greetings & pleasantries
        small_talk_patterns = [
            r"^(hi|hello|hey|hiya|hola|howdy)(\s+(there|everyone|all|guys|sir|ma'am|team))?$",
            r"^(good\s+(morning|afternoon|evening|day))(\s+(everyone|all|guys|sir|ma'am|team))?$",
            r"^(how\s+are\s+you(\s+doing)?(\s+today)?)$",
            r"^(how(\')?s\s+it\s+going)$",
            r"^(hope\s+you(\')?re\s+doing\s+well)$",
            r"^(nice|great|glad)\s+to\s+meet\s+you$",
            r"^(yes|yeah|yep|yup|sure|okay|ok|alright|right|cool|fine|perfect|awesome|great|understood|got\s+it|uh-huh|no\s+problem|sounds\s+good|of\s+course)$",
            r"^(thank\s+you(\s+very\s+much|\s+so\s+much)?|thanks(\s+a\s+lot)?)$",
            r"^(you(\')?re\s+welcome)$",
            r"^(let(\')?s\s+(start|begin|get\s+started|proceed|continue|wait(\s+a\s+(minute|second))?))$",
            r"^(shall\s+we\s+(start|begin|get\s+started))$",
            r"^(welcome\s+to\s+the\s+interview)$",
            r"^(give\s+me\s+a\s+(second|sec|moment))$",
            r"^(hold\s+on(\s+a\s+(second|moment))?)$"
        ]

        for pat in small_talk_patterns:
            if re.match(pat, cleaned, re.IGNORECASE):
                return True

        # 5. Short fillers: if 3 or fewer words and all are common filler/greeting words
        words = cleaned.split()
        greeting_words = {
            "hi", "hello", "hey", "good", "morning", "afternoon", "evening",
            "yes", "yeah", "yep", "yup", "no", "nope", "okay", "ok", "alright",
            "sure", "great", "cool", "fine", "thanks", "thank", "you", "welcome",
            "bye", "testing", "one", "two", "three", "audible", "sound", "check"
        }
        if len(words) <= 3 and all(w in greeting_words for w in words):
            return True

        return False

    def _build_system_instruction(self, mode: str = "auto") -> str:
        """
        Construct dynamic, resume-grounded system instruction with automatic question classification:
        - Auto-identifies career domain from Resume, Profile, and Target Job Description.
        - Automatically detects question intent: Coding/DSA, Behavioral (STAR), System Design, or Technical Concepts.
        - Delivers direct spoken answers ready for the candidate to speak verbatim.
        """
        base_instruction = (
            "You are an elite AI Technical Interview Copilot assisting a senior candidate in a live technical interview.\n"
            "MANDATORY LANGUAGE ENFORCEMENT:\n"
            "1. 100% PURE PROFESSIONAL ENGLISH ONLY: You MUST generate every response strictly in fluent, clear, grammatically flawless, authoritative ENGLISH.\n"
            "   NEVER output answers in Hindi, Hinglish, regional accents, or mixed languages, even if the transcribed question contains Hindi words or colloquial phrasing. Always respond in articulate, professional English.\n"
            "\n"
            "DOMAIN & CAREER GROUNDING (DYNAMICALLY ADAPTED FROM RESUME & PROFILE):\n"
            "1. RESUME-GROUNDED IDENTITY: Speak authentically from the candidate's professional seniority, stack, and background as documented in their Resume and Profile.\n"
            "   - If the candidate's resume/JD reflects QA / SDET / Software Testing: Ground terminology strictly in Software Testing (e.g. ISTQB standards, Bug Life Cycle, Severity vs. Priority, Test Automation frameworks like Selenium/Playwright/REST Assured, TestNG/JUnit, BDD Cucumber, API testing).\n"
            "   - If the candidate's resume/JD reflects Software Engineering / Fullstack / Backend / Frontend / DevOps / Data: Ground answers strictly in modern software engineering principles, clean architecture, high scalability, and their specific tech stack.\n"
            "\n"
            "DYNAMIC QUESTION CLASSIFICATION & ADAPTIVE RESPONSE RULES:\n"
            "The candidate does not manually switch category dropdowns during a live interview. You must AUTOMATICALLY recognize the question type and format your answer accordingly:\n"
            "\n"
            f"1. CODING, DSA & AUTOMATION SCRIPTING QUESTIONS (e.g., algorithms, writing functions, coding challenges, automation scripts):\n"
            f"   - Output clean, working, production-grade {self.preferred_language.upper()} code enclosed in markdown ```{self.preferred_language}.\n"
            "   - In 1-2 direct spoken sentences, state the core intuition, optimal Time & Space complexity.\n"
            "   - Mention 1 critical edge case or assertion strategy to impress the interviewer.\n"
            "\n"
            "2. BEHAVIORAL & HR QUESTIONS (e.g., 'tell me about a time...', 'describe a conflict/challenge...', 'why should we hire you...', 'tell me about yourself'):\n"
            "   - Deliver a direct first-person story matching the candidate's actual projects and experience from their uploaded resume.\n"
            "   - Structure using the STAR method (Situation, Task, Action, Result) in under 4 connected, natural spoken sentences.\n"
            "   - Conclude with a clear, measurable positive impact (e.g., 'prevented a production outage', 'reduced test cycle time by 40%').\n"
            "\n"
            "3. SYSTEM DESIGN & ARCHITECTURE QUESTIONS (e.g., 'how would you design...', 'scale this service...', 'microservices vs monolith...'):\n"
            "   - Deliver direct architectural decisions in 3-4 structured spoken sentences:\n"
            "     * Direct architecture choice, APIs, and primary data storage.\n"
            "     * Bottleneck mitigation (caching, message queues, async processing).\n"
            "     * Scaling, resilience, and trade-offs.\n"
            "\n"
            "4. TECHNICAL CONCEPTUAL & DEFINITION QUESTIONS (e.g., 'explain...', 'difference between X and Y', 'what is...'):\n"
            "   - STRICT DIRECT SPOKEN STATEMENT FORMAT (ZERO FILLER, NO PREAMBLE):\n"
            "     * NEVER begin with 'Well, in my experience...', 'Basically...', 'Sure, I can explain that', or restate the question.\n"
            "     * Sentence 1: Direct, precise technical definition answering the question immediately.\n"
            "     * Sentence 2: Core mechanism, how it works under the hood, or primary advantage.\n"
            "     * Sentence 3: Key trade-off or practical production consideration.\n"
            "     * Sentence 4: One specific production pattern or real-world example from the candidate's domain.\n"
            "   - NO BULLET POINTS OR TEXTBOOK HEADINGS for conceptual answers: Keep as 3-4 connected direct sentences so the candidate can read them aloud smoothly without sounding like an AI reading bullet lists.\n"
            "   - NO ROBOTIC PLEASANTRIES: Never say 'Here is the answer', 'Sure!', or 'As an AI'. Deliver direct first-person statements.\n"
        )

        context_section = ""
        candidate_details = []
        if getattr(self, "candidate_name", ""):
            candidate_details.append(f"Name: {self.candidate_name}")
        if getattr(self, "candidate_email", ""):
            candidate_details.append(f"Email: {self.candidate_email}")
        if getattr(self, "candidate_phone", ""):
            candidate_details.append(f"Phone: {self.candidate_phone}")
        if candidate_details:
            context_section += f"\nCANDIDATE PERSONAL DETAILS:\n" + "\n".join(candidate_details) + "\n"
        if self.resume_text:
            context_section += f"\nCANDIDATE RESUME CONTEXT (Reference relevant experience when applicable):\n{self.resume_text[:2500]}\n"
        if self.job_description:
            context_section += f"\nTARGET JOB DESCRIPTION CONTEXT:\n{self.job_description[:1500]}\n"

        mode_rules = ""
        if mode == "coding":
            mode_rules = f"\nSPECIAL OVERRIDE: Focus heavily on {self.preferred_language.upper()} code solution and complexity.\n"
        elif mode == "behavioral":
            mode_rules = "\nSPECIAL OVERRIDE: Focus heavily on first-person STAR story from resume.\n"
        elif mode == "system_design":
            mode_rules = "\nSPECIAL OVERRIDE: Focus heavily on high-level system architecture and scaling trade-offs.\n"
        elif mode == "qa_testing":
            mode_rules = "\nSPECIAL OVERRIDE: Prioritize QA, SDET, and test automation context.\n"

        if self.custom_instructions:
            context_section += f"\nUSER CUSTOM INSTRUCTIONS (Apply when consistent with the interview question and system requirements):\n{self.custom_instructions}\n"
        if self.google_search_enabled:
            context_section += "\nCURRENT INFORMATION: Use the available Google Search grounding tool when the question depends on current facts, versions, or recent events. Distinguish sourced facts from estimates.\n"

        return base_instruction + context_section + mode_rules

    def _call_groq_chat(self, question: str, system_instruction: str) -> Optional[Dict[str, Any]]:
        """Attempt to answer via Groq with rolling conversation history."""
        if not self.groq_client:
            return None

        # Build message chain with rolling context
        messages = [{"role": "system", "content": system_instruction}]
        for turn in self.conversation_history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": question})

        for model in self.groq_models:
            try:
                response = self.groq_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1500
                )
                answer = response.choices[0].message.content or ""
                if answer.strip():
                    self.add_turn("user", question)
                    self.add_turn("assistant", answer.strip())
                    return {
                        "success": True,
                        "answer": answer.strip(),
                        "model_used": f"Groq ({model})",
                        "provider": "Groq"
                    }
            except Exception as e:
                err_str = str(e)
                logger.warning(f"Groq model {model} failed or rate-limited: {err_str}")
                continue
        return None

    def _call_gemini_chat(self, question: str, system_instruction: str) -> Optional[Dict[str, Any]]:
        """Attempt to answer via Gemini with rolling conversation context."""
        if not self.client:
            return None

        candidate_models = [self.gemini_primary_model] + [m for m in self.gemini_fallback_models if m != self.gemini_primary_model]
        from google.genai import types

        history_context = ""
        if self.conversation_history:
            history_context = "RECENT CONVERSATION CONTEXT:\n" + "\n".join([
                f"{'Candidate' if t['role'] == 'user' else 'Copilot'}: {t['content'][:400]}"
                for t in self.conversation_history
            ]) + "\n\nCURRENT QUESTION:\n"

        prompt_with_history = f"{history_context}{question}" if history_context else question

        for model in candidate_models:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt_with_history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        tools=[types.Tool(google_search=types.GoogleSearch())] if self.google_search_enabled else None,
                    )
                )
                answer = (response.text or "").strip()
                if answer:
                    self.add_turn("user", question)
                    self.add_turn("assistant", answer)
                    return {
                        "success": True,
                        "answer": answer,
                        "model_used": f"Gemini ({model})",
                        "provider": "Google Gemini"
                    }
            except Exception as e:
                logger.warning(f"Gemini model {model} failed: {e}")
                continue
        return None

    def ask_question(self, question: str, mode: str = "auto", speaker: str = "Candidate") -> Dict[str, Any]:
        """
        Process a question with automatic multi-provider failover:
        1. Try Groq (Ultra-fast, ~0.6s response).
        2. If Groq hits 30 RPM or fails -> Automatically switch to Gemini!
        3. If Gemini hits quota -> Automatically switch to Groq!
        """
        if not self.groq_client and not self.client:
            return {
                "success": False,
                "error": AI_ACCESS_DENIED_MESSAGE
            }

        system_instruction = self._build_system_instruction(mode)

        # 1. Try Groq first for lightning-fast sub-second response
        if self.groq_client and not self.google_search_enabled:
            res = self._call_groq_chat(question, system_instruction)
            if res and res.get("success"):
                res["mode"] = mode
                res["question"] = question
                res["speaker"] = speaker
                return res
            logger.info("⚡ Groq unavailable or rate-limited. Seamlessly falling back to Google Gemini...")

        # 2. Fallback to Gemini
        if self.client:
            res = self._call_gemini_chat(question, system_instruction)
            if res and res.get("success"):
                res["mode"] = mode
                res["question"] = question
                res["speaker"] = speaker
                return res

        # 3. If Gemini failed first and Groq wasn't tried yet, try Groq
        if not self.groq_client and self.client:
            res = self._call_gemini_chat(question, system_instruction)
            if res and res.get("success"):
                res["mode"] = mode
                res["question"] = question
                res["speaker"] = speaker
                return res

        return {
            "success": False,
            "error": "All AI providers (Groq & Gemini) temporarily exhausted rate limits or encountered an error. Please try again in a few seconds."
        }


    def solve_screen_snip(self, image_bytes: bytes, user_prompt: str = "", mode: str = "coding") -> Dict[str, Any]:
        """
        Multimodal OCR & Problem Solver:
        Takes a screenshot of LeetCode / Code challenge,
        extracts problem, constraints, and returns complete optimal solution.
        """
        if not self.client:
            if not self.api_key:
                return {
                    "success": False,
                    "error": AI_ACCESS_DENIED_MESSAGE
                }
            self.initialize_gemini()
            if not self.client:
                return {"success": False, "error": "Unable to connect to Copilot. Please check your internet connection."}

        system_instruction = self._build_system_instruction(mode)
        candidate_models = [self.gemini_primary_model] + [m for m in self.gemini_fallback_models if m != self.gemini_primary_model]

        prompt = (
            f"Analyze this coding problem / interview question from the screenshot.\n"
            f"1. Identify the problem name, input/output, and constraints.\n"
            f"2. Provide the optimal algorithm intuition.\n"
            f"3. Provide full, clean, working {self.preferred_language.upper()} code solution.\n"
            f"4. Give Time & Space Complexity.\n"
            f"{('Additional candidate instruction: ' + user_prompt) if user_prompt else ''}"
        )

        try:
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            return {"success": False, "error": f"Invalid image data: {e}"}

        last_error = ""
        for model in candidate_models:
            try:
                from google.genai import types

                response = self.client.models.generate_content(
                    model=model,
                    contents=[prompt, image],
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                    )
                )

                ans = response.text or ""
                self.add_turn("user", f"[Screen Snipped Problem]: {user_prompt or 'Analyze and solve code on screen'}")
                self.add_turn("assistant", ans)

                return {
                    "success": True,
                    "answer": ans,
                    "mode": mode,
                    "is_screenshot": True,
                    "speaker": "Screen Vision",
                    "model_used": f"Gemini Vision ({model})"
                }
            except Exception as e:
                logger.warning(f"Vision model {model} failed: {e}. Trying fallback...")
                last_error = str(e)

        return {"success": False, "error": self.sanitize_error(last_error, "Vision Analysis")}

    def solve_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav", mode: str = "coding", speaker: str = "Interviewer") -> Dict[str, Any]:
        """
        High-Speed Interviewer & Candidate Audio Processing:
        1. If Groq is active: Transcribes audio in ~200ms with Groq Whisper (whisper-large-v3-turbo).
           Then answers via Groq Llama/Qwen or Gemini.
        2. If Groq Whisper is unavailable or fails: Falls back to Gemini direct audio understanding.
        """
        # Determine correct audio extension for Whisper API
        lower_mime = (mime_type or "audio/wav").lower()
        if "webm" in lower_mime:
            audio_filename = "audio.webm"
        elif "ogg" in lower_mime:
            audio_filename = "audio.ogg"
        elif "mp4" in lower_mime or "m4a" in lower_mime:
            audio_filename = "audio.m4a"
        else:
            audio_filename = "audio.wav"

        # --- PATH 1: Groq Whisper Ultra-Fast Transcription ---
        if self.groq_client:
            try:
                logger.info(f"Transcribing {speaker.lower()} audio ({audio_filename}) with Groq Whisper...")
                transcription = self.groq_client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=(audio_filename, audio_bytes, mime_type),
                    response_format="text",
                    language="en",
                    prompt="Software testing, QA, SDET, automation, severity, priority, defect, bug life cycle, Selenium, Playwright, API, test cases, regression, smoke, sanity, Postman, test suite"
                )
                text = (transcription if isinstance(transcription, str) else getattr(transcription, "text", "")).strip()
                logger.info(f"Groq Whisper transcribed ({speaker}): '{text}'")

                # 1. Filter noise / silence hallucinations
                noise_patterns = [
                    r"^thank you\.?$",
                    r"^you\.?$",
                    r"^thanks for watching\.?$",
                    r"^subtitles by",
                    r"^\s*$"
                ]
                is_noise = any(re.match(pat, text, re.IGNORECASE) for pat in noise_patterns)

                if is_noise or len(text) < 3:
                    logger.info("Audio was background noise or empty. Discarding.")
                    return {"success": False, "error": "No clear question detected in audio."}

                # 2. Strict Filter for Small Talk/Greetings only for Interviewer (Candidate explicitly used PTT!)
                if speaker == "Interviewer" and self.is_small_talk_or_greeting(text):
                    logger.info(f"🚫 [TOKEN SAVER] Interviewer greeting/chitchat detected: '{text}'. Dropping without LLM call.")
                    return {
                        "success": False,
                        "is_small_talk": True,
                        "transcribed_text": text,
                        "error": f"Interviewer greeting/chitchat detected: '{text}'. Waiting for technical question..."
                    }

                # Now generate answer with specified speaker
                result = self.ask_question(text, mode=mode, speaker=speaker)
                if result.get("success"):
                    result["is_audio"] = True
                    result["transcribed_question"] = text
                    result["speaker"] = speaker
                    result["model_used"] = f"Whisper + {result.get('model_used', '')}"
                    return result

            except Exception as e:
                logger.warning(f"Groq Whisper transcription failed or rate-limited: {e}. Falling back to Gemini audio...")

        # --- PATH 2: Gemini Direct Audio Multimodal Fallback ---
        if self.client:
            try:
                system_instruction = self._build_system_instruction(mode)
                candidate_models = [self.gemini_primary_model] + [m for m in self.gemini_fallback_models if m != self.gemini_primary_model]

                from google.genai import types
                audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

                prompt = (
                    f"Listen carefully to this interview audio spoken by the {speaker}.\n"
                    "CRITICAL: If the audio is silent, unintelligible, background noise/static, OR is merely a greeting/small talk/mic check (e.g. 'hi', 'hello', 'can you hear me', 'good morning', 'testing', 'okay', 'yeah'), respond ONLY with: 'NO_CLEAR_QUESTION'. Do NOT answer greetings.\n"
                    f"If a clear, substantive interview question or prompt was spoken:\n"
                    "NOTE: The interview domain is strictly SOFTWARE TESTING, QUALITY ASSURANCE (QA), SDET, AND SOFTWARE ENGINEERING.\n"
                    "MANDATORY: Output MUST BE 100% FLUENT PROFESSIONAL ENGLISH ONLY. Transcribe the question in clean English and provide the answer in professional English.\n"
                    "1. First line: Question: \"<exact question transcribed in English>\"\n"
                    "2. Direct, spoken technical answer in 3-4 punchy sentences that the candidate can read aloud immediately. No conversational filler or meta-talk."
                )

                for model in candidate_models:
                    try:
                        response = self.client.models.generate_content(
                            model=model,
                            contents=[prompt, audio_part],
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                temperature=0.2,
                            )
                        )

                        raw_text = (response.text or "").strip()
                        if "NO_CLEAR_QUESTION" in raw_text:
                            logger.info("Gemini detected no clear question in audio.")
                            return {"success": False, "error": "No clear question detected in audio."}

                        self.add_turn("user", f"[{speaker} Audio Question]: {raw_text[:200]}")
                        self.add_turn("assistant", raw_text)

                        return {
                            "success": True,
                            "answer": raw_text,
                            "mode": mode,
                            "is_audio": True,
                            "speaker": speaker,
                            "model_used": f"Gemini Audio ({model})"
                        }

                    except Exception as e:
                        logger.warning(f"Gemini audio model {model} failed: {e}. Trying fallback...")
                        continue

            except Exception as e:
                logger.error(f"Gemini audio fallback failed: {e}")

        return {"success": False, "error": "Could not process interviewer audio."}
