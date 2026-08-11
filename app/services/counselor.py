"""Chat orchestration.

One entry point, ``respond()``, which ties together risk assessment, prompting,
memory, generation and persistence. Routes stay thin; this is where the actual
behaviour of the product lives.

A hard rule runs through this module: **the user always gets a reply.** If the
model errors, times out, or is not configured, they get a real, human-sounding
fallback -- and if the assessment said crisis, they get the crisis resources
regardless of what the model did. There is no path where someone types "I want
to die" and receives a stack trace or silence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..extensions import db
from ..models import Conversation, Message, MoodEntry, RiskLevel, utcnow
from . import memory as memory_service
from . import safety
from .hf_client import GenerationError
from .prompts import GUEST_NOTICE, build_system_prompt

logger = logging.getLogger(__name__)


# Used when generation fails outside a crisis. Deliberately an invitation to
# keep talking rather than an error message.
_FALLBACK_BY_RISK = {
    RiskLevel.NONE: (
        "I'm having trouble finding the right words just now — a technical hiccup on my "
        "end, not anything you said. Tell me a bit more about what's going on?"
    ),
    RiskLevel.LOW: (
        "I'm having a bit of trouble responding properly right now, and I don't want that "
        "to stop you. What's weighing on you most at the moment?"
    ),
    RiskLevel.MODERATE: (
        "I'm struggling to respond the way I'd like to right now, but I don't want you to "
        "feel brushed off — what you're describing sounds genuinely heavy. If it keeps "
        "feeling this way, talking to someone qualified could really help. I'm still here."
    ),
}


@dataclass
class Reply:
    text: str
    assessment: safety.RiskAssessment
    resources: list[dict] = field(default_factory=list)
    fallback_used: bool = False
    conversation_id: int | None = None
    # The user's own safety plan, surfaced at high risk. Empty otherwise.
    safety_plan: dict | None = None
    # True when risk is high and no plan exists yet, so the UI can offer one.
    offer_safety_plan: bool = False

    def to_dict(self) -> dict:
        return {
            "response": self.text,
            "risk": self.assessment.to_dict(),
            "resources": self.resources,
            "degraded": self.fallback_used or self.assessment.degraded,
            "conversation_id": self.conversation_id,
            "safety_plan": self.safety_plan,
            "offer_safety_plan": self.offer_safety_plan,
        }


def respond(
    user_input: str,
    *,
    hf,
    config,
    user=None,
    guest_history: list[dict] | None = None,
) -> Reply:
    """Produce one assistant turn.

    ``user`` set  -> conversation is loaded from and written to the database.
    ``user`` None -> guest mode; history comes from the caller and nothing is stored.
    """
    user_input = (user_input or "").strip()
    if not user_input:
        raise ValueError("user_input must not be empty")

    classifier = hf if getattr(hf, "configured", False) else None
    assessment = safety.assess(user_input, classifier)

    conversation: Conversation | None = None
    summary: str | None = None
    user_name: str | None = None

    if user is not None:
        conversation = memory_service.get_or_create_conversation(user.id)
        summary = conversation.summary
        user_name = user.username

    system_prompt = build_system_prompt(
        assessment, user_name=user_name, summary=summary
    )
    if user is None:
        system_prompt = f"{system_prompt}\n\n{GUEST_NOTICE}"

    window = config["MEMORY_TURN_WINDOW"]
    if conversation is not None:
        messages = memory_service.build_prompt_messages(
            conversation, system_prompt, user_input, window
        )
    else:
        messages = memory_service.build_guest_messages(
            system_prompt, guest_history or [], user_input, window
        )

    # At imminent risk, a long reply is the wrong reply. Cap it hard.
    max_tokens = 160 if assessment.level >= RiskLevel.IMMINENT else config["LLM_MAX_TOKENS"]
    temperature = 0.4 if assessment.is_crisis else config["LLM_TEMPERATURE"]

    fallback_used = False
    try:
        text = hf.chat(messages, max_tokens=max_tokens, temperature=temperature)
    except GenerationError as exc:
        logger.error("Generation failed (risk=%s): %s", assessment.level.label, exc)
        fallback_used = True
        text = (
            safety.CRISIS_FALLBACK_MESSAGE
            if assessment.is_crisis
            else _FALLBACK_BY_RISK.get(assessment.level, _FALLBACK_BY_RISK[RiskLevel.NONE])
        )

    # Resources are attached by the application, never left to the model to
    # remember. A generated reply that forgets the helpline is not acceptable.
    resources: list[dict] = []
    if assessment.needs_resources:
        resources = safety.CRISIS_RESOURCES if assessment.is_crisis else safety.CRISIS_RESOURCES[:3]

    reply = Reply(
        text=text,
        assessment=assessment,
        resources=resources,
        fallback_used=fallback_used,
    )

    # At high risk, put the person's own safety plan in front of them. In a
    # crisis, recall narrows and generic advice slides off; their own words,
    # written calmly, land differently. Guests have no stored plan.
    if user is not None and assessment.level >= RiskLevel.HIGH:
        _attach_safety_plan(reply, user)

    if user is not None and conversation is not None:
        _persist(conversation, user, user_input, reply, assessment)
        reply.conversation_id = conversation.id
        try:
            memory_service.maybe_summarise(
                conversation,
                hf,
                trigger=config["MEMORY_SUMMARY_TRIGGER"],
                window=window,
            )
        except Exception:  # summarisation must never break a served reply
            logger.exception("Summarisation raised for conversation %s", conversation.id)
            db.session.rollback()

    return reply


def _attach_safety_plan(reply: Reply, user) -> None:
    """Surface the user's plan, or invite them to make one.

    The invitation is deliberately withheld at IMMINENT risk: asking someone
    with a plan and means to go and fill in a form is the wrong instruction at
    that moment. Contacting a human is the only thing that should compete for
    their attention.
    """
    from ..models import SafetyPlan  # local import keeps services import-light

    try:
        plan = db.session.query(SafetyPlan).filter(SafetyPlan.user_id == user.id).first()
    except Exception:
        logger.exception("Could not load safety plan for user %s", user.id)
        return

    if plan is not None and not plan.is_empty:
        reply.safety_plan = plan.crisis_extract()
    elif reply.assessment.level < RiskLevel.IMMINENT:
        reply.offer_safety_plan = True


def _persist(
    conversation: Conversation,
    user,
    user_input: str,
    reply: Reply,
    assessment: safety.RiskAssessment,
) -> None:
    try:
        db.session.add(
            Message(
                conversation_id=conversation.id,
                role="user",
                content=user_input,
                risk_level=int(assessment.level),
            )
        )
        db.session.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content=reply.text,
                risk_level=int(assessment.level),
            )
        )
        db.session.add(
            MoodEntry(
                user_id=user.id,
                sentiment=assessment.sentiment,
                sentiment_score=assessment.sentiment_score,
                emotions=",".join(assessment.emotions)[:255] or None,
                risk_level=int(assessment.level),
                excerpt=user_input[:500],
            )
        )
        if conversation.title in (None, "", "Conversation"):
            # First real message doubles as the conversation's label.
            conversation.title = user_input[:80]
        # Touch the row so "most recently active conversation" ordering is real.
        conversation.updated_at = utcnow()
        db.session.commit()
    except Exception:
        # Losing the transcript is bad. Failing the user's request because we
        # could not write it is worse -- they already have their answer.
        logger.exception("Failed to persist turn for conversation %s", conversation.id)
        db.session.rollback()
