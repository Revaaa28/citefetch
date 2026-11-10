"""Question understanding: target value type + content keywords."""
import re

STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "is", "are", "was", "were", "the", "a", "an", "of", "for", "in", "on",
    "at", "to", "by", "and", "or", "does", "do", "did", "can", "could",
    "please", "tell", "me", "find", "give", "show", "get", "current",
    "latest", "with", "from", "that", "this", "it", "its", "as", "be",
}

# Ordered: the first type whose triggers appear wins.
_TYPE_TRIGGERS = [
    ("email", ["email", "e-mail", "mail address"]),
    ("phone", ["phone", "telephone", "fax number", "call centre", "call center"]),
    ("price", ["price", "cost", "how much", "fee", "fees", "rent", "salary",
               "worth in", "$", "usd", "tuition"]),
    ("date", ["when", "date", "born", "founded", "established", "released",
              "launched", "invented", "died", "year was", "what year",
              "what day", "anniversary"]),
    ("name", ["who", "name of", "founder", "founded by", "ceo", "author",
              "inventor", "creator", "created by", "written by", "director",
              "president", "designed by", "developed by", "singer", "actor"]),
    ("number", ["how many", "how old", "how long", "how far", "how tall",
                "version", "population", "number of", "percent", "percentage",
                "employees", "height", "weight", "distance", "speed",
                "temperature", "rating", "score", "count"]),
]


def classify(query):
    """Return one of: price, date, phone, email, name, number, other."""
    q = " " + query.lower() + " "
    for vtype, triggers in _TYPE_TRIGGERS:
        for trig in triggers:
            if trig in q:
                return vtype
    return "other"


def question_keywords(query):
    """Content words of the question, used for proximity scoring."""
    tokens = re.findall(r"[a-z0-9][a-z0-9'.-]*", query.lower())
    keywords = []
    for tok in tokens:
        tok = tok.strip("'.-")
        if len(tok) >= 3 and tok not in STOPWORDS and tok not in keywords:
            keywords.append(tok)
    return keywords
