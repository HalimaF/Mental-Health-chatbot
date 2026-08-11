"""Risk assessment.

The original implementation was eight substring checks against a lowercased
string. It missed every indirect disclosure ("I don't want to be here
anymore"), every Roman-Urdu phrasing, and it fired on "I watched a documentary
about suicide" -- showing a user in no distress a red emergency banner, which
is its own kind of harm.

This module replaces it with two independent layers that are fused, never
substituted for one another:

  Layer 1 -- deterministic rules. Pure Python, no network, no model download,
             runs in microseconds. Always executes. This is what keeps the app
             safe when Hugging Face is slow, rate-limiting, or down.

  Layer 2 -- Hugging Face classifiers. A suicide-risk model plus emotion and
             sentiment models, over the Inference API. Catches the phrasings no
             keyword list will ever enumerate.

The fused level is ``max(rules, classifier)`` with one exception: clearly
informational or third-party text is capped unless the classifier is highly
confident. Under-reacting is dangerous; over-reacting teaches people to ignore
the banner, which is also dangerous.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..models import RiskLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer 1: deterministic rules
# ---------------------------------------------------------------------------

def _pattern(*fragments: str) -> re.Pattern:
    return re.compile("|".join(fragments), re.IGNORECASE | re.UNICODE)


# Stated intent with a plan, means, or timeframe. The most urgent signal there is.
IMMINENT_PATTERNS = _pattern(
    r"\b(?:i(?:'m| am)? ?(?:going to|gonna|about to)) (?:kill myself|end (?:it|my life)|die)\b",
    r"\b(?:tonight|today|tomorrow|right now|in an hour) i(?:'m| am| will| wil)?\b[^.]{0,30}\b(?:die|end it|kill myself)\b",
    r"\bi (?:have|got|bought|collected|saved up) (?:the )?(?:pills|rope|gun|blade|razor|knife|poison)\b",
    r"\b(?:wrote|writing|written|left) (?:my |a )?(?:suicide )?note\b",
    r"\bthis is (?:my )?goodbye\b",
    r"\bi(?:'ve| have) (?:already )?(?:taken|swallowed) (?:the |all the )?pills\b",
    r"\bi (?:have|made) a plan to (?:die|kill myself|end)\b",
    r"\bsaying goodbye (?:to everyone|forever)\b",
)

# Direct suicidal ideation or self-harm, without a stated plan.
HIGH_PATTERNS = _pattern(
    r"\bkill(?:ing)? myself\b",
    # Third-person phrasing still describes suicidal intent and must register.
    # The third-party rule below decides whose risk it is; this decides that
    # there is risk at all. Without it, "my flatmate is killing herself" scored
    # NONE because only the first-person form was listed.
    r"\bkill(?:ing)? (?:him|her|them|it)self\b",
    r"\bend(?:ing)? (?:his|her|their) life\b",
    r"\bend(?:ing)? my life\b",
    r"\btake my own life\b",
    r"\bcommit suicide\b",
    r"\bsuicidal\b",
    # Deliberately not anchored to "I" -- "used to want to die" and "he wants to
    # die" must both match here so the negation and third-party rules below can
    # decide what they mean. Anchoring on the pronoun silently dropped both.
    r"\bwant(?:s|ed)? to die\b",
    r"\bwanna die\b",
    r"\bwish i (?:was|were) dead\b",
    r"\bwish i (?:had )?never (?:been )?born\b",
    r"\bbetter off (?:dead|without me)\b",
    r"\b(?:everyone|they|the world) would be better (?:off )?(?:without|if i)\b",
    r"\bdon'?t want to (?:be here|live|exist|wake up)\b",
    r"\bdo not want to (?:be here|live|exist)\b",
    r"\bno (?:point|reason) (?:in )?(?:living|being here|going on)\b",
    # Allow any words between subject and verb: "I have been cutting myself".
    r"\b(?:cut|cutting|burn|burning|hurt|hurting|harm|harming|starv|starving)\w*\s+myself\b",
    r"\bself[- ]harm(?:ing|ed)?\b",
    r"\bend it all\b",
    r"\bwant it (?:all )?to (?:be over|end|stop)\b",
    # Urdu script and Roman Urdu -- the app's primary audience is Pakistani.
    r"خودکشی",
    r"مرنا چاہتا",
    r"جینے کا دل نہیں",
    r"\bkhud ?kush(?:i|ee)\b",
    r"\bkhudkashi\b",
    r"\bmarna chahta\b",
    r"\bmarna chahti\b",
    r"\bmar jana chahta\b",
    r"\bjeena nahi(?:n)? chahta\b",
    r"\bjeena nahi(?:n)? chahti\b",
    r"\bzindagi khatam\b",
    r"\bmujhe marna\b",
)

# Hopelessness, entrapment, burdensomeness: established precursors, not intent.
MODERATE_PATTERNS = _pattern(
    r"\bhopeless\b",
    r"\bworthless\b",
    r"\bi(?:'m| am) a burden\b",
    r"\bburden to (?:everyone|my family|them)\b",
    r"\bcan'?t (?:go on|take it|do this) (?:anymore|any more|any longer)\b",
    r"\bno way out\b",
    r"\bnothing (?:matters|will ever change|ever gets better)\b",
    r"\bi(?:'m| am) trapped\b",
    r"\bgiving up\b",
    r"\bgive up on (?:life|everything)\b",
    r"\bempty inside\b",
    r"\bnumb\b",
    r"\bno one (?:cares|would notice|would miss me)\b",
    r"\bcompletely alone\b",
    r"\bcan'?t stop crying\b",
    r"\bumeed (?:khatam|nahi)\b",
    r"\bbohat akela\b",
)

# General distress. Worth acknowledging, not worth escalating.
LOW_PATTERNS = _pattern(
    r"\b(?:depress(?:ed|ion)|anxious|anxiety|panic attack|overwhelm(?:ed|ing))\b",
    r"\b(?:stressed|exhausted|burn(?:t|ed) out|insomnia|can'?t sleep)\b",
    r"\b(?:lonely|grieving|heartbroken|scared|afraid)\b",
    r"\bpareshan\b",
    r"\budaas\b",
)

# "I used to want to die", "you helped me not want to die" -- past tense and
# negation invert the meaning entirely.
NEGATION_PATTERNS = _pattern(
    r"\b(?:don'?t|do not|never|no longer|not) (?:want|wanted|going|feel like)[^.]{0,20}\b(?:die|kill myself|suicidal|end it)\b",
    r"\b(?:used to|previously|once|before) [^.]{0,25}\b(?:want(?:ed)? to die|kill myself|suicidal)\b",
    r"\b(?:glad|happy|grateful|thankful) (?:i|that i)[^.]{0,25}\bdidn'?t\b",
    r"\bstopped (?:feeling|being|wanting)\b[^.]{0,25}\b(?:suicidal|to die)\b",
    r"\bno longer (?:suicidal|want to die)\b",
    r"\bi(?:'m| am) not suicidal\b",
    r"\bnot going to (?:kill myself|hurt myself|do anything)\b",
)

# Text about suicide rather than a disclosure of it.
INFORMATIONAL_PATTERNS = _pattern(
    r"\bsuicide (?:prevention|hotline|helpline|awareness|rates?|statistics|research)\b",
    r"\b(?:documentary|article|movie|film|book|paper|study|news|podcast|essay|assignment|report) (?:about|on)\b",
    r"\bwriting (?:a|an) (?:essay|paper|story|report|assignment)\b",
    r"\bfor (?:my|a) (?:class|school|university|thesis|homework|project)\b",
    r"\bwhat (?:is|are) the (?:signs|symptoms|warning)\b",
    # "How do I help my sister who wants to die" is a real person in danger, not
    # an academic question. It belongs to the third-party rule, which supports
    # the helper; treating it as informational capped it at LOW and withheld
    # the resources they were explicitly asking for.
)

# Someone else's crisis. Still serious, but the response differs: support the
# helper and give them referral routes rather than treating them as at-risk.
THIRD_PARTY_PATTERNS = _pattern(
    # Household and peer relations matter as much as family here -- a student
    # worried about a roommate is one of the most common versions of this
    # message, and omitting the word meant it was handled as the user's own risk.
    r"\bmy (?:friend|best friend|brother|sister|sibling|mother|father|mom|mum|dad|"
    r"son|daughter|child|kid|cousin|aunt|uncle|niece|nephew|partner|husband|wife|"
    r"fiance[e]?|girlfriend|boyfriend|roommate|room[- ]?mate|flatmate|housemate|"
    r"classmate|coursemate|batchmate|colleague|coworker|co[- ]worker|neighbou?r|"
    r"student|patient|client|teammate|cousin sister|cousin brother)\b",
    r"\bmy (?:younger|older|little|big|elder) (?:brother|sister|cousin)\b",
    r"\b(?:he|she|they) (?:is|are|was|were|said|says|told me|keeps?|has been)\b[^.]{0,40}"
    r"\b(?:suicidal|kill (?:him|her|them)self|want(?:s|ed)? to die|end (?:his|her|their) life)\b",
    r"\bsomeone (?:i know|close to me|in my (?:family|class|hostel))\b",
    r"\bhow (?:do|can|should) i (?:help|support|talk to) (?:my|him|her|them|someone)\b",
    r"\bworried about (?:my|him|her|them|someone)\b",
)


@dataclass
class RiskAssessment:
    level: RiskLevel = RiskLevel.NONE
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    emotions: list[str] = field(default_factory=list)
    # Which layers contributed, for auditing and for the tests.
    signals: list[str] = field(default_factory=list)
    rule_level: RiskLevel = RiskLevel.NONE
    model_level: RiskLevel = RiskLevel.NONE
    model_score: float = 0.0
    third_party: bool = False
    informational: bool = False
    degraded: bool = False  # true when the HF layer was unavailable

    @property
    def is_crisis(self) -> bool:
        return self.level >= RiskLevel.HIGH

    @property
    def needs_resources(self) -> bool:
        return self.level >= RiskLevel.MODERATE

    def to_dict(self) -> dict:
        return {
            "level": self.level.label,
            "level_value": int(self.level),
            "sentiment": self.sentiment,
            "emotions": self.emotions,
            "is_crisis": self.is_crisis,
            "third_party": self.third_party,
            "degraded": self.degraded,
        }


def assess_with_rules(text: str) -> RiskAssessment:
    """Layer 1. Deterministic, offline, always available."""
    assessment = RiskAssessment()
    if not text or not text.strip():
        return assessment

    informational = bool(INFORMATIONAL_PATTERNS.search(text))
    third_party = bool(THIRD_PARTY_PATTERNS.search(text))
    negated = bool(NEGATION_PATTERNS.search(text))

    if IMMINENT_PATTERNS.search(text):
        level = RiskLevel.IMMINENT
        assessment.signals.append("rule:imminent")
    elif HIGH_PATTERNS.search(text):
        level = RiskLevel.HIGH
        assessment.signals.append("rule:ideation")
    elif MODERATE_PATTERNS.search(text):
        level = RiskLevel.MODERATE
        assessment.signals.append("rule:hopelessness")
    elif LOW_PATTERNS.search(text):
        level = RiskLevel.LOW
        assessment.signals.append("rule:distress")
    else:
        level = RiskLevel.NONE

    # A negated or past-tense disclosure -- "I no longer want to die", "I used to
    # want to die but therapy helped", "I'm not suicidal, just tired" -- is a
    # recovery or reassurance statement, not a disclosure. Drop to LOW: still
    # worth a warm, attentive reply, but no emergency banner over good news.
    if negated and level >= RiskLevel.HIGH:
        level = RiskLevel.LOW
        assessment.signals.append("rule:negated")

    # Asking about suicide is not disclosing it. Never escalate past LOW on
    # rules alone -- but the classifier can still override upward below.
    if informational and level >= RiskLevel.MODERATE:
        level = RiskLevel.LOW
        assessment.signals.append("rule:informational")

    # Worry about someone else is real distress, but it is not the user's own
    # risk. Step it down one notch rather than dismissing it.
    if third_party and level >= RiskLevel.HIGH:
        level = RiskLevel.MODERATE
        assessment.signals.append("rule:third_party")

    assessment.level = assessment.rule_level = level
    assessment.informational = informational
    assessment.third_party = third_party
    return assessment


def _model_level_from_score(score: float) -> RiskLevel:
    if score >= 0.90:
        return RiskLevel.HIGH
    if score >= 0.75:
        return RiskLevel.MODERATE
    if score >= 0.55:
        return RiskLevel.LOW
    return RiskLevel.NONE


# Emotions from the go_emotions label set that carry clinical weight.
_CONCERNING_EMOTIONS = {"grief", "sadness", "fear", "nervousness", "remorse", "disappointment"}


def assess(text: str, classifier=None) -> RiskAssessment:
    """Full pipeline: rules fused with Hugging Face classifiers.

    ``classifier`` is any object exposing ``suicide_score``, ``emotions`` and
    ``sentiment``. Passing ``None`` yields a rules-only assessment flagged as
    ``degraded`` -- which is exactly what happens when HF is unreachable.
    """
    assessment = assess_with_rules(text)

    if classifier is None:
        assessment.degraded = True
        return assessment

    try:
        score = classifier.suicide_score(text)
        emotions = classifier.emotions(text)
        sentiment, sentiment_score = classifier.sentiment(text)
    except Exception as exc:  # network, rate limit, cold start, bad model id
        logger.warning("Classifier layer unavailable, falling back to rules: %s", exc)
        assessment.degraded = True
        return assessment

    assessment.model_score = score
    assessment.model_level = _model_level_from_score(score)
    assessment.emotions = emotions
    assessment.sentiment = sentiment
    assessment.sentiment_score = sentiment_score
    if assessment.model_level > RiskLevel.NONE:
        assessment.signals.append(f"model:suicide={score:.2f}")

    fused = max(assessment.rule_level, assessment.model_level)

    # Informational text needs strong model evidence before it is escalated --
    # a student researching suicide prevention should not get a crisis banner.
    if assessment.informational and score < 0.90:
        fused = min(fused, RiskLevel.LOW)

    # Same logic for a negated disclosure.
    if "rule:negated" in assessment.signals and score < 0.90:
        fused = min(fused, RiskLevel.LOW)

    # Strong negative affect nudges a flat reading upward, never past MODERATE.
    if fused <= RiskLevel.LOW and set(emotions) & _CONCERNING_EMOTIONS and score >= 0.5:
        fused = max(fused, RiskLevel.LOW)

    assessment.level = fused
    return assessment


# ---------------------------------------------------------------------------
# Crisis resources
# ---------------------------------------------------------------------------

CRISIS_RESOURCES = [
    {"name": "Emergency Services (Pakistan)", "contact": "15 or 1122", "type": "emergency"},
    {"name": "Umang Mental Health Helpline", "contact": "0311-7786264", "type": "helpline"},
    {"name": "Rozan Counselling Helpline", "contact": "0304-1111741", "type": "helpline"},
    {"name": "Taskeen Health Initiative", "contact": "https://taskeen.org", "type": "directory"},
    {"name": "Crisis Text Line (International)", "contact": "Text HOME to 741741", "type": "text"},
    {
        "name": "Find a helpline in your country",
        "contact": "https://findahelpline.com",
        "type": "directory",
    },
]

# Used verbatim when the language model is unreachable during a crisis. There
# is no acceptable failure mode where a user in crisis receives nothing.
CRISIS_FALLBACK_MESSAGE = (
    "I'm really glad you told me, and I want you to know I'm taking what you said "
    "seriously. What you're carrying sounds unbearably heavy, and you shouldn't have "
    "to carry it alone right now.\n\n"
    "I'm an AI, so I can't be the support you need in this moment — but a person can be. "
    "Please reach out to one of the numbers below, or to someone nearby you trust. "
    "If you are in immediate danger, call 15 or 1122 now.\n\n"
    "I'm still here, and I'll keep listening for as long as you want to talk."
)

THIRD_PARTY_GUIDANCE = (
    "It says a lot about you that you're looking for ways to help them. "
    "The most useful things you can do are: ask directly and calmly whether they're "
    "thinking about suicide (asking does not plant the idea — research is clear on "
    "this), listen without rushing to fix it, and help them connect with a "
    "professional. Please don't carry this alone either."
)
