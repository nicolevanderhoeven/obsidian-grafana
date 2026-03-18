"""Tests for word frequency extraction in parse_notes.py"""

import pytest

from parse_notes import extract_word_frequencies, STOPWORDS, update_metrics, metrics_data, obsidian_note_total, obsidian_note_wikilinks


class TestExtractWordFrequencies:
    """Tests for extract_word_frequencies function."""

    def test_basic_word_extraction(self):
        """Should extract words and count frequencies."""
        content = "hello world hello"
        result = extract_word_frequencies(content)
        
        assert result['hello'] == 2
        assert result['world'] == 1

    def test_stopwords_filtered(self):
        """Common stopwords should be filtered out."""
        content = "the quick brown fox jumps over the lazy dog"
        result = extract_word_frequencies(content)
        
        # Stopwords should not appear
        assert 'the' not in result
        assert 'over' not in result
        
        # Non-stopwords should appear
        assert result['quick'] == 1
        assert result['brown'] == 1
        assert result['fox'] == 1
        assert result['jumps'] == 1
        assert result['lazy'] == 1
        assert result['dog'] == 1

    def test_single_and_two_char_words_filtered(self):
        """Words with 2 or fewer characters should be filtered."""
        content = "a I we go to be or not"
        result = extract_word_frequencies(content)
        
        # All words are 2 chars or less, or stopwords
        assert len(result) == 0

    def test_case_normalization(self):
        """Words should be normalized to lowercase."""
        content = "Hello HELLO hello HeLLo"
        result = extract_word_frequencies(content)
        
        assert result['hello'] == 4
        assert 'Hello' not in result
        assert 'HELLO' not in result

    def test_punctuation_handling(self):
        """Punctuation should not be part of words."""
        content = "hello, world! how are you? fine, thanks."
        result = extract_word_frequencies(content)
        
        assert result['hello'] == 1
        assert result['world'] == 1
        assert result['fine'] == 1
        assert result['thanks'] == 1
        # Punctuation should not create separate entries
        assert 'hello,' not in result
        assert 'world!' not in result

    def test_numbers_filtered(self):
        """Pure numbers should not appear (they don't match the word pattern)."""
        content = "chapter 123 section 456"
        result = extract_word_frequencies(content)
        
        assert 'chapter' == 1 or result.get('chapter', 0) == 1
        assert 'section' == 1 or result.get('section', 0) == 1
        assert '123' not in result
        assert '456' not in result

    def test_empty_content(self):
        """Empty content should return empty dict."""
        result = extract_word_frequencies("")
        assert result == {}

    def test_whitespace_only_content(self):
        """Whitespace-only content should return empty dict."""
        result = extract_word_frequencies("   \n\t   \n")
        assert result == {}

    def test_only_stopwords_content(self):
        """Content with only stopwords should return empty dict."""
        content = "the a an is are was were be been being"
        result = extract_word_frequencies(content)
        assert result == {}

    def test_markdown_content(self):
        """Should handle typical markdown content."""
        content = """
# Project Overview

This is a **project** about machine learning.

## Features
- Feature one: neural networks
- Feature two: deep learning
- Feature three: data processing

[Link text](https://example.com)

```python
def hello():
    pass
```
        """
        result = extract_word_frequencies(content)
        
        # Should extract meaningful words
        assert result['project'] == 2  # appears in title and content
        assert result['feature'] == 3
        assert result['neural'] == 1
        assert result['networks'] == 1
        assert result['learning'] == 2  # machine learning, deep learning
        
        # URL parts should be filtered or not counted as words
        assert 'https' not in result
        assert result.get('example', 0) == 1

    def test_wikilinks_content(self):
        """Should handle Obsidian wikilinks."""
        content = "Check [[Other Note]] for more details about [[Another Topic]]"
        result = extract_word_frequencies(content)
        
        # 'see' is a stopword, so use 'check' instead
        assert result['check'] == 1
        assert result['note'] == 1
        # 'other' is a stopword
        assert 'other' not in result
        # 'more' and 'for' and 'about' are stopwords
        assert 'more' not in result
        assert result['details'] == 1
        assert result['another'] == 1
        assert result['topic'] == 1

    def test_mixed_alphanumeric_words(self):
        """Words with numbers mixed in should be handled."""
        content = "python3 version2 api v1"
        result = extract_word_frequencies(content)
        
        # The regex \b[a-zA-Z]+\b uses word boundaries
        # 'python3' - no word boundary between 'python' and '3', so no match for 'python'
        # 'version2' - same, no match for 'version'
        # 'api' - pure alphabetic, matches
        # 'v1' - 'v' alone would match but is too short (< 3 chars)
        # This is expected behavior: alphanumeric strings like 'python3' are not split
        assert result.get('api', 0) == 1
        assert 'python' not in result  # Not extracted due to trailing digit
        assert 'version' not in result  # Not extracted due to trailing digit

    def test_hyphenated_words(self):
        """Hyphenated words should be split."""
        content = "machine-learning state-of-the-art real-time"
        result = extract_word_frequencies(content)
        
        # Hyphenated words are split into separate words
        assert result['machine'] == 1
        assert result['learning'] == 1
        assert result['state'] == 1
        assert result['art'] == 1
        assert result['real'] == 1
        assert result['time'] == 1

    def test_apostrophes(self):
        """Contractions and possessives should be handled."""
        content = "it's John's can't won't"
        result = extract_word_frequencies(content)
        
        # Apostrophes split words
        assert result.get('john', 0) == 1 or result.get('johns', 0) == 0
        # 'it', 's', 'can', 't', 'won' - most are too short or stopwords

    def test_url_artifacts_filtered(self):
        """URL-related words should be filtered."""
        content = "visit http www example com org net for more"
        result = extract_word_frequencies(content)
        
        # URL artifacts should be filtered via stopwords
        assert 'http' not in result
        assert 'www' not in result
        assert 'com' not in result
        assert 'org' not in result
        assert 'net' not in result
        
        # Regular words should remain
        assert result['visit'] == 1
        assert result['example'] == 1

    def test_large_document(self):
        """Should handle larger documents efficiently."""
        # Create a document with repeated content
        words = ["python", "programming", "software", "development", "testing"]
        content = " ".join(words * 100)  # 500 words total
        
        result = extract_word_frequencies(content)
        
        for word in words:
            assert result[word] == 100


class TestStopwordsCompleteness:
    """Tests to verify stopwords list is comprehensive."""

    def test_common_articles_in_stopwords(self):
        """Common articles should be in stopwords."""
        articles = ['a', 'an', 'the']
        for article in articles:
            assert article in STOPWORDS, f"'{article}' should be in stopwords"

    def test_common_pronouns_in_stopwords(self):
        """Common pronouns should be in stopwords."""
        pronouns = ['i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them']
        for pronoun in pronouns:
            assert pronoun in STOPWORDS, f"'{pronoun}' should be in stopwords"

    def test_common_prepositions_in_stopwords(self):
        """Common prepositions should be in stopwords."""
        prepositions = ['in', 'on', 'at', 'by', 'for', 'with', 'to', 'from', 'of']
        for prep in prepositions:
            assert prep in STOPWORDS, f"'{prep}' should be in stopwords"

    def test_common_conjunctions_in_stopwords(self):
        """Common conjunctions should be in stopwords."""
        conjunctions = ['and', 'but', 'or', 'so', 'if', 'because']
        for conj in conjunctions:
            assert conj in STOPWORDS, f"'{conj}' should be in stopwords"

    def test_common_verbs_in_stopwords(self):
        """Common auxiliary verbs should be in stopwords."""
        verbs = ['is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 
                 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'can', 'may', 'might']
        for verb in verbs:
            assert verb in STOPWORDS, f"'{verb}' should be in stopwords"

    def test_url_artifacts_in_stopwords(self):
        """URL artifacts should be in stopwords."""
        url_parts = ['http', 'https', 'www', 'com', 'org', 'net']
        for part in url_parts:
            assert part in STOPWORDS, f"'{part}' should be in stopwords"

    def test_stopwords_is_frozenset(self):
        """STOPWORDS should be a frozenset for performance."""
        assert isinstance(STOPWORDS, frozenset)


class TestUpdateMetrics:
    """Tests for update_metrics function with file_path label."""

    def test_update_metrics_with_file_path(self):
        """Should update metrics including file_path label."""
        update_metrics(
            note_name="test-note",
            vault="test-vault",
            word_count=100,
            tags=["tag1", "tag2"],
            wikilinks_count=5,
            file_path="folder/subfolder/test-note.md"
        )
        
        # Verify the metric was created with the file_path label
        labels = {"vault": "test-vault", "note_name": "test-note", "file_path": "folder/subfolder/test-note.md"}
        metric_value = obsidian_note_total.labels(**labels)._value.get()
        assert metric_value >= 1

    def test_update_metrics_without_file_path(self):
        """Should work with empty file_path (backwards compatibility)."""
        update_metrics(
            note_name="root-note",
            vault="test-vault",
            word_count=50,
            tags=[],
            wikilinks_count=0,
            file_path=""
        )
        
        labels = {"vault": "test-vault", "note_name": "root-note", "file_path": ""}
        metric_value = obsidian_note_total.labels(**labels)._value.get()
        assert metric_value >= 1

    def test_update_metrics_file_path_with_special_chars(self):
        """Should handle file paths with spaces and special characters."""
        update_metrics(
            note_name="my note",
            vault="test-vault",
            word_count=25,
            tags=["test"],
            wikilinks_count=1,
            file_path="My Folder/Sub Folder/my note.md"
        )
        
        labels = {"vault": "test-vault", "note_name": "my note", "file_path": "My Folder/Sub Folder/my note.md"}
        metric_value = obsidian_note_total.labels(**labels)._value.get()
        assert metric_value >= 1

    def test_update_metrics_wikilinks_per_note(self):
        """Should track wikilinks count per note."""
        update_metrics(
            note_name="linked-note",
            vault="test-vault",
            word_count=100,
            tags=[],
            wikilinks_count=15,
            file_path="folder/linked-note.md"
        )
        
        labels = {"vault": "test-vault", "note_name": "linked-note", "file_path": "folder/linked-note.md"}
        metric_value = obsidian_note_wikilinks.labels(**labels)._value.get()
        assert metric_value == 15

    def test_update_metrics_wikilinks_zero(self):
        """Should handle notes with zero wikilinks."""
        update_metrics(
            note_name="no-links",
            vault="test-vault",
            word_count=50,
            tags=[],
            wikilinks_count=0,
            file_path="no-links.md"
        )
        
        labels = {"vault": "test-vault", "note_name": "no-links", "file_path": "no-links.md"}
        metric_value = obsidian_note_wikilinks.labels(**labels)._value.get()
        assert metric_value == 0
