"""Tests for the risk assessment pipeline.

These matter more than any other test in the suite: a regression here means a
person in crisis is handled as though they were fine, or someone researching a
school assignment is shown an emergency banner.
"""

from __future__ import annotations

import pytest

from app.models import RiskLevel
from app.services import safety


class StubClassifier:
    def __init__(self, score=0.0, emotions=None, sentiment=("neutral", 0.5), boom=False):
        self._score, self._emotions, self._sentiment, self._boom = (
            score, emotions or [], sentiment, boom,
        )

    def suicide_score(self, text):
        if self._boom:
            raise RuntimeError("HF is down")
        return self._score

    def emotions(self, text):
        return self._emotions

    def sentiment(self, text):
        return self._sentiment


# --- Layer 1: rules --------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "I'm going to kill myself tonight",
        "i have the pills ready",
        "I wrote my note already",
        "this is my goodbye",
        "I am going to end it all tomorrow",
    ],
)
def test_imminent_intent_is_detected(text):
    assert safety.assess_with_rules(text).level == RiskLevel.IMMINENT


@pytest.mark.parametrize(
    "text",
    [
        "I want to die",
        "I don't want to be here anymore",
        "everyone would be better off without me",
        "there is no point in living",
        "I've been cutting myself again",
        "I have been hurting myself",
        "I wish I was dead",
        "mujhe marna hai",
        "jeena nahi chahta",
        "خودکشی",  # khudkushi, Urdu script
    ],
)
def test_ideation_is_detected(text):
    """Every one of these was missed by the original eight-keyword check."""
    assert safety.assess_with_rules(text).level == RiskLevel.HIGH


@pytest.mark.parametrize(
    "text",
    [
        "I feel completely hopeless",
        "I'm such a burden to everyone",
        "I can't go on anymore",
        "there is no way out",
        "nothing ever gets better",
    ],
)
def test_hopelessness_is_moderate(text):
    assert safety.assess_with_rules(text).level == RiskLevel.MODERATE


@pytest.mark.parametrize(
    "text",
    [
        "I've been really anxious about my exams",
        "I'm so stressed and exhausted",
        "I can't sleep at all lately",
    ],
)
def test_ordinary_distress_is_low(text):
    assert safety.assess_with_rules(text).level == RiskLevel.LOW


@pytest.mark.parametrize(
    "text",
    ["I got the job today!", "what's the weather like", "tell me a joke"],
)
def test_neutral_text_is_not_flagged(text):
    assert safety.assess_with_rules(text).level == RiskLevel.NONE


# --- False-positive suppression -------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "I used to want to die but therapy really helped",
        "I'm not suicidal, just tired",
        "I no longer want to die",
        "I'm glad I didn't go through with it",
    ],
)
def test_negated_and_past_tense_disclosures_are_not_crises(text):
    a = safety.assess_with_rules(text)
    assert a.level <= RiskLevel.LOW
    assert not a.is_crisis


@pytest.mark.parametrize(
    "text",
    [
        "I'm writing an essay about suicide prevention for my class",
        "what are the warning signs of suicide in teenagers",
        "I watched a documentary about suicide last night",
    ],
)
def test_informational_questions_do_not_trigger_crisis(text):
    """The original code showed a red emergency banner for all of these."""
    a = safety.assess_with_rules(text)
    assert not a.is_crisis


def test_third_party_concern_is_stepped_down_and_flagged():
    a = safety.assess_with_rules("My brother said he wants to die, how do I help him?")
    assert a.third_party is True
    assert a.level == RiskLevel.MODERATE
    assert not a.is_crisis


# --- Layer 2 fusion --------------------------------------------------------

def test_classifier_escalates_phrasing_rules_miss():
    text = "everything feels like it is closing in and I cannot see a way forward"
    assert safety.assess_with_rules(text).level < RiskLevel.HIGH
    fused = safety.assess(text, StubClassifier(score=0.95))
    assert fused.level == RiskLevel.HIGH


def test_rules_win_when_classifier_is_confident_it_is_fine():
    """A model shrug must never downgrade an explicit disclosure."""
    fused = safety.assess("I want to kill myself", StubClassifier(score=0.01))
    assert fused.level >= RiskLevel.HIGH
    assert fused.is_crisis


def test_informational_text_needs_strong_model_evidence_to_escalate():
    text = "I'm researching suicide prevention for my psychology paper"
    fused = safety.assess(text, StubClassifier(score=0.80))
    assert not fused.is_crisis


def test_classifier_failure_degrades_to_rules_instead_of_raising():
    fused = safety.assess("I want to die", StubClassifier(boom=True))
    assert fused.degraded is True
    assert fused.level == RiskLevel.HIGH  # rule layer still caught it


def test_no_classifier_still_assesses():
    fused = safety.assess("I want to kill myself", None)
    assert fused.degraded is True
    assert fused.is_crisis


def test_empty_input_is_safe():
    assert safety.assess_with_rules("").level == RiskLevel.NONE
    assert safety.assess_with_rules("   ").level == RiskLevel.NONE


def test_assessment_serialises_for_the_api():
    d = safety.assess("I want to die", None).to_dict()
    assert d["level"] == "high"
    assert d["is_crisis"] is True
    assert set(d) >= {"level", "level_value", "sentiment", "emotions", "is_crisis"}


def test_risk_levels_are_ordered():
    assert (
        RiskLevel.NONE < RiskLevel.LOW < RiskLevel.MODERATE
        < RiskLevel.HIGH < RiskLevel.IMMINENT
    )
