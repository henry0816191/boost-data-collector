"""
Shared text cleaning and light filtering helpers.

Used by ``cppa_slack_tracker`` (and other apps) for normalizing message text and
optional greeting/noise phrase removal. Default word lists are Slack-oriented
(``SLACK_*`` constants).
"""

from __future__ import annotations

import html
import re
from typing import Iterable, FrozenSet, Optional

# Default greeting/unessential words for filter_sentence (Slack message cleaning)
SLACK_GREETING_WORDS: FrozenSet[str] = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "greetings",
        "howdy",
        "sup",
        "what's up",
        "yo",
        "hii",
        "helloo",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "appreciate it",
        "cheers",
        "nice to meet you",
        "happy to be here",
        "happy to have you here",
        "glad to see you",
        "glad to see you here",
        "glad to be here",
        "bye",
        "goodbye",
        "see you later",
        "see you soon",
        "see you tomorrow",
        "see you next week",
        "see you next month",
        "see you next year",
        "see you in the future",
    }
)

SLACK_UNESSENTIAL_WORDS: FrozenSet[str] = frozenset(
    {
        "ok",
        "okay",
        "sure",
        "yeah",
        "yep",
        "yup",
        "nope",
        "nah",
        "lol",
        "haha",
        "hahaha",
        "hehe",
        "lmao",
        "rofl",
        "👍",
        "👎",
        "😊",
        "😄",
        "😀",
        "👍🏻",
        "👌",
        "got it",
        "gotcha",
        "nice",
        "awesome",
        "great",
        "uhm",
        "um",
        "uh",
        "erm",
        "of course",
    }
)


def clean_text(text: str | None, remove_extra_spaces: bool = True) -> str:
    """
    Clean and normalize text content.

    Removes invisible characters, decodes HTML character references (e.g.
    ``&amp;``, ``&#39;``, ``&#x2f;``), fixes a few common bare entities without
    ``;``, normalizes line breaks, and optionally removes extra whitespace.

    Args:
        text: Input text to clean
        remove_extra_spaces: Whether to remove extra whitespace

    Returns:
        Cleaned text

    Examples:
        >>> clean_text("  Hello   world  ")
        'Hello world'
        >>> clean_text("Text\\n\\n\\nMore text")
        'Text\\n\\nMore text'
    """
    if not text:
        return ""

    # Remove soft hyphens and other invisible characters
    text = (
        text.replace("\xad", "")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\xa0", " ")
        .replace("\u2002", " ")
        .replace("\u2003", " ")
        .replace("\u2026", "...")
        .replace("\u202f", " ")
    )

    text = html.unescape(text)

    # Normalize line breaks
    text = re.sub(r"\r\n", "\n", text)  # Windows line breaks
    text = re.sub(r"\r", "\n", text)  # Old Mac line breaks

    if remove_extra_spaces:
        text = re.sub(r" +", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.strip() for line in text.split("\n"))

    return text.strip()


def filter_sentence(
    sentence: str,
    greeting_words: Optional[Iterable[str]] = None,
    unessential_words: Optional[Iterable[str]] = None,
    min_words_after: int = 3,
) -> str:
    """
    Filter a single sentence by removing greeting/unessential words.

    Removes phrases from greeting_words and unessential_words (case-insensitive),
    then returns the stripped sentence, or "" if too few words remain.

    Args:
        sentence: Input sentence to filter.
        greeting_words: Phrases to remove (e.g. "hi", "thank you"). Default: SLACK_GREETING_WORDS.
        unessential_words: Phrases to remove (e.g. "ok", "lol"). Default: SLACK_UNESSENTIAL_WORDS.
        min_words_after: Minimum word count to keep (inclusive); return "" if fewer. Default: 3.

    Returns:
        Filtered sentence (lowercased, stripped), or "" if empty or fewer than min_words_after words.

    Examples:
        >>> filter_sentence("Hi there, can you help?")
        'there, can you help?'
        >>> filter_sentence("ok sure")
        ''
    """
    sentence = sentence.strip()
    if not sentence:
        return ""

    greeting = (
        {word.lower() for word in greeting_words}
        if greeting_words is not None
        else SLACK_GREETING_WORDS
    )
    unessential = (
        {word.lower() for word in unessential_words}
        if unessential_words is not None
        else SLACK_UNESSENTIAL_WORDS
    )

    sentence_lower = sentence.lower()
    removable_phrases = sorted(greeting | unessential, key=len, reverse=True)
    for phrase in removable_phrases:
        pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
        sentence_lower = re.sub(pattern, "", sentence_lower)

    sentence_lower = re.sub(r"\s{2,}", " ", sentence_lower).strip()

    if len(sentence_lower.strip().split()) < min_words_after:
        return ""

    return sentence_lower.strip()


def validate_content_length(content: str | None, min_length: int = 50) -> bool:
    """
    Validate that content meets minimum length requirement.

    Args:
        content: Content string to validate
        min_length: Minimum required length (default: 50)

    Returns:
        True if content is valid, False otherwise

    Examples:
        >>> validate_content_length("This is a short text")
        False
        >>> validate_content_length("This is a much longer text that exceeds the minimum length requirement")
        True
    """
    if not content:
        return False

    cleaned = content.strip()
    return len(cleaned) >= min_length
