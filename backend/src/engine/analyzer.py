"""Spanish analyzer of the lexical index: lower case, no accents, no stopwords
and light stemming (plural and gender only), so that "licitaciones públicas"
finds "licitación pública"."""
from __future__ import annotations

from src.text.tokens import tokens

STOPWORDS = frozenset(
    """a al algo algun alguna algunas alguno algunos ante antes como con contra cual cuales cuando de del demas desde
    donde durante e el ella ellas ellos en entre era eran es esa esas ese eso esos esta estaba estan estar este esto
    estos fue fueron ha haber habia han hasta hay la las le les lo los mas me mi mientras muy ni no nos nosotros o os
    otra otras otro otros para pero poco por porque que quien quienes se sea sean ser si sido sin sobre son su sus tal
    tambien tan tanto te tener tiene tienen todo todos tras tu tus u un una unas uno unos y ya yo""".split()
)
MIN_STEMMED = 5


def stem(word: str) -> str:
    """The light stemmer of Savoy for Spanish, on words without accents."""
    if len(word) < MIN_STEMMED or word[-1].isdigit():
        return word
    if word[-1] in "oae":
        return word[:-1]
    if word[-1] == "s":
        if word.endswith("eses") and len(word) > 6:  # "interes" becomes "inter", and "intereses" has to follow
            return word[:-4]
        if word.endswith("ces"):
            return word[:-3] + "z"
        if word[-2] in "oa" and len(word) == MIN_STEMMED:  # "obras": its singular is too short to lose its vowel
            return word[:-1]
        if word[-2] in "oae":
            return word[:-2]
    return word


def analyze(text: str) -> list[str]:
    return [stem(t) for t in tokens(text) if t not in STOPWORDS]
