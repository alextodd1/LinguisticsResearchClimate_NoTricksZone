"""
Text tokenization for Sketch Engine vertical format.
"""

import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Try to import spacy or nltk
TOKENIZER_BACKEND = None

try:
    import spacy
    TOKENIZER_BACKEND = 'spacy'
except ImportError:
    try:
        import nltk
        from nltk.tokenize import sent_tokenize, word_tokenize
        TOKENIZER_BACKEND = 'nltk'
    except ImportError:
        logger.warning("Neither spaCy nor NLTK available, using basic tokenizer")
        TOKENIZER_BACKEND = 'basic'


class Tokeniser:
    """
    Tokeniser for Sketch Engine vertical format.

    Splits text into sentences and tokens.
    """

    def __init__(self, backend: Optional[str] = None):
        """
        Initialize tokeniser.

        Args:
            backend: 'spacy', 'nltk', or 'basic'. Auto-detects if None.
        """
        self.backend = backend or TOKENIZER_BACKEND
        self.nlp = None

        if self.backend == 'spacy':
            self._init_spacy()
        elif self.backend == 'nltk':
            self._init_nltk()

    def _init_spacy(self):
        """Initialize spaCy model."""
        try:
            import spacy
            # Try to load English model
            try:
                self.nlp = spacy.load('en_core_web_sm')
            except OSError:
                logger.info("Downloading spaCy English model...")
                from spacy.cli import download
                download('en_core_web_sm')
                self.nlp = spacy.load('en_core_web_sm')

            # Disable unnecessary components for speed
            self.nlp.disable_pipes(['ner', 'parser', 'lemmatizer'])
            # Add sentencizer
            if 'sentencizer' not in self.nlp.pipe_names:
                self.nlp.add_pipe('sentencizer')

        except Exception as e:
            logger.error(f"Failed to initialize spaCy: {e}")
            self.backend = 'basic'

    def _init_nltk(self):
        """Initialize NLTK tokenizers."""
        try:
            import nltk
            # Ensure punkt is downloaded
            try:
                nltk.data.find('tokenizers/punkt')
            except LookupError:
                nltk.download('punkt', quiet=True)
                nltk.download('punkt_tab', quiet=True)
        except Exception as e:
            logger.error(f"Failed to initialize NLTK: {e}")
            self.backend = 'basic'

    def tokenize(self, text: str) -> List[List[str]]:
        """
        Tokenize text into sentences and words.

        Args:
            text: Text to tokenize

        Returns:
            List of sentences, each sentence is a list of tokens
        """
        if not text or not text.strip():
            return []

        if self.backend == 'spacy':
            return self._tokenize_spacy(text)
        elif self.backend == 'nltk':
            return self._tokenize_nltk(text)
        else:
            return self._tokenize_basic(text)

    def _tokenize_spacy(self, text: str) -> List[List[str]]:
        """Tokenize using spaCy."""
        sentences = []

        # Process in chunks for very long texts
        max_length = 100000
        chunks = [text[i:i + max_length] for i in range(0, len(text), max_length)]

        for chunk in chunks:
            doc = self.nlp(chunk)
            for sent in doc.sents:
                tokens = [token.text for token in sent if not token.is_space]
                if tokens:
                    sentences.append(tokens)

        return sentences

    def _tokenize_nltk(self, text: str) -> List[List[str]]:
        """Tokenize using NLTK."""
        from nltk.tokenize import sent_tokenize, word_tokenize

        sentences = []

        for sent in sent_tokenize(text):
            tokens = word_tokenize(sent)
            if tokens:
                sentences.append(tokens)

        return sentences

    def _tokenize_basic(self, text: str) -> List[List[str]]:
        """Basic tokenization without external libraries."""
        sentences = []

        # Split on sentence boundaries
        sent_pattern = re.compile(r'(?<=[.!?])\s+')
        raw_sents = sent_pattern.split(text)

        for sent in raw_sents:
            sent = sent.strip()
            if not sent:
                continue

            # Basic word tokenization
            # Separate punctuation from words
            tokens = re.findall(r'\b\w+\b|[^\w\s]', sent)
            if tokens:
                sentences.append(tokens)

        return sentences

    def tokenize_to_vertical(self, text: str) -> str:
        """
        Tokenize text and format for vertical output.

        Args:
            text: Text to tokenize

        Returns:
            Vertical format string with <s> tags and one token per line
        """
        sentences = self.tokenize(text)
        lines = []

        for sent_tokens in sentences:
            lines.append('<s>')
            for token in sent_tokens:
                # Escape special XML characters
                token = token.replace('&', '&amp;')
                token = token.replace('<', '&lt;')
                token = token.replace('>', '&gt;')
                lines.append(token)
            lines.append('</s>')

        return '\n'.join(lines)

    def tokenize_paragraphs(self, paragraphs: List[str]) -> str:
        """
        Tokenize multiple paragraphs with paragraph markers.

        Args:
            paragraphs: List of paragraph texts

        Returns:
            Vertical format string with <p> and <s> tags
        """
        lines = []

        for para in paragraphs:
            if not para.strip():
                continue

            lines.append('<p>')
            para_vertical = self.tokenize_to_vertical(para)
            lines.append(para_vertical)
            lines.append('</p>')

        return '\n'.join(lines)
