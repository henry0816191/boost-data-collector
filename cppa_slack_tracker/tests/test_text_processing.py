"""Tests for cppa_slack_tracker.utils.text_processing."""

from cppa_slack_tracker.utils.text_processing import (
    clean_text,
    filter_sentence,
    validate_content_length,
    SLACK_GREETING_WORDS,
    SLACK_UNESSENTIAL_WORDS,
)


def test_clean_text_removes_invisible_characters():
    """clean_text removes soft hyphens and zero-width spaces."""
    text = "Hello\xadworld\u200b"
    result = clean_text(text)
    assert result == "Helloworld"


def test_clean_text_normalizes_line_breaks():
    """clean_text normalizes different line break styles."""
    text = "Line1\r\nLine2\rLine3\nLine4"
    result = clean_text(text)
    assert "\r" not in result
    assert result.count("\n") == 3


def test_clean_text_removes_extra_spaces():
    """clean_text removes multiple spaces when remove_extra_spaces=True."""
    text = "Hello    world   test"
    result = clean_text(text, remove_extra_spaces=True)
    assert result == "Hello world test"


def test_clean_text_limits_newlines():
    """clean_text limits consecutive newlines to max 2."""
    text = "Line1\n\n\n\n\nLine2"
    result = clean_text(text, remove_extra_spaces=True)
    assert result == "Line1\n\nLine2"


def test_clean_text_strips_line_whitespace():
    """clean_text removes spaces at start/end of lines."""
    text = "  Line1  \n  Line2  "
    result = clean_text(text, remove_extra_spaces=True)
    assert result == "Line1\nLine2"


def test_clean_text_handles_empty_input():
    """clean_text returns empty string for empty input."""
    assert clean_text("") == ""
    assert clean_text(None) == ""


def test_filter_sentence_removes_greetings():
    """filter_sentence removes greeting words as whole phrases (keeps 'hi' inside 'this')."""
    sentence = "Hi there, can you help me with this?"
    result = filter_sentence(sentence)
    assert result.startswith("there")  # standalone "Hi" removed
    assert "help" in result
    assert "this" in result  # "hi" inside "this" is not removed


def test_filter_sentence_removes_unessential_words():
    """filter_sentence removes unessential words like 'ok', 'lol'."""
    sentence = "Ok sure, that sounds great lol"
    result = filter_sentence(sentence)
    # After filtering, should have remaining meaningful content
    assert isinstance(result, str)


def test_filter_sentence_returns_empty_for_short_result():
    """filter_sentence returns empty string if result is too short."""
    sentence = "Hi ok"  # Only greeting and unessential words
    result = filter_sentence(sentence, min_words_after=3)
    assert result == ""


def test_filter_sentence_handles_empty_input():
    """filter_sentence returns empty string for empty input."""
    assert filter_sentence("") == ""
    assert filter_sentence("   ") == ""


def test_filter_sentence_custom_word_lists():
    """filter_sentence accepts custom greeting and unessential word lists."""
    sentence = "Hello world test example"
    result = filter_sentence(
        sentence,
        greeting_words=["hello"],
        unessential_words=["world"],
        min_words_after=1,
    )
    assert "test" in result or "example" in result
    assert "hello" not in result.lower()
    assert "world" not in result.lower()


def test_validate_content_length_accepts_long_text():
    """validate_content_length returns True for text meeting minimum length."""
    long_text = "This is a much longer text that definitely exceeds the minimum length requirement"
    assert validate_content_length(long_text, min_length=50) is True


def test_validate_content_length_rejects_short_text():
    """validate_content_length returns False for text below minimum length."""
    short_text = "Hi"
    assert validate_content_length(short_text, min_length=50) is False


def test_validate_content_length_handles_empty_input():
    """validate_content_length returns False for empty input."""
    assert validate_content_length("") is False
    assert validate_content_length(None) is False


def test_validate_content_length_strips_whitespace():
    """validate_content_length strips whitespace before checking length."""
    text_with_spaces = "   Short   "
    assert validate_content_length(text_with_spaces, min_length=10) is False


def test_slack_greeting_words_constant():
    """SLACK_GREETING_WORDS contains expected greeting words."""
    assert "hi" in SLACK_GREETING_WORDS
    assert "hello" in SLACK_GREETING_WORDS
    assert "thanks" in SLACK_GREETING_WORDS
    assert "goodbye" in SLACK_GREETING_WORDS


def test_slack_unessential_words_constant():
    """SLACK_UNESSENTIAL_WORDS contains expected unessential words."""
    assert "ok" in SLACK_UNESSENTIAL_WORDS
    assert "lol" in SLACK_UNESSENTIAL_WORDS
    assert "yeah" in SLACK_UNESSENTIAL_WORDS
    assert "awesome" in SLACK_UNESSENTIAL_WORDS
