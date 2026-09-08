"""
spaCy model loader. Singleton — model is loaded only once per process.
"""
import logging
from functools import lru_cache

import spacy

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_nlp():
    """
    Load the spaCy model once and cache it.
    Subsequent calls return the same cached instance.
    """
    try:
        nlp = spacy.load('en_core_web_sm')
        logger.info("spaCy model loaded: en_core_web_sm")
        return nlp
    except OSError:
        logger.error(
            "spaCy model 'en_core_web_sm' not found. "
            "Run: python -m spacy download en_core_web_sm"
        )
        raise