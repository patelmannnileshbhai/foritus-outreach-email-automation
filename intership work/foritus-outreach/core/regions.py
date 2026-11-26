"""Country -> language / tone / conventions."""

EN_US = {"code": "en-US", "lang": "en", "language": "English", "spelling": "US", "formality": "friendly-direct",
         "tone": "Friendly, concise and direct. American spelling. First-name basis. Get to the point quickly."}
EN_GB = {"code": "en-GB", "lang": "en", "language": "English", "spelling": "UK", "formality": "polite-understated",
         "tone": "Polite, understated and courteous. British spelling. Avoid hard-sell and superlatives."}
EN_AU = {"code": "en-AU", "lang": "en", "language": "English", "spelling": "UK", "formality": "casual-direct",
         "tone": "Relaxed, straightforward and down-to-earth. British/Australian spelling. No corporate jargon."}
EN_IN = {"code": "en-IN", "lang": "en", "language": "English", "spelling": "UK", "formality": "respectful-warm",
         "tone": "Respectful and warm, slightly more formal. British spelling. Courteous phrasing."}
EN_ME = {"code": "en-ME", "lang": "en", "language": "English", "spelling": "UK", "formality": "formal-relationship",
         "tone": "Formal, respectful and relationship-oriented. British spelling. Courteous, unhurried."}
EN_INT = {"code": "en", "lang": "en", "language": "English", "spelling": "UK", "formality": "neutral-professional",
          "tone": "Neutral, clear and professional international English with simple vocabulary."}
DE = {"code": "de", "lang": "de", "language": "German", "spelling": "", "formality": "formal-concise",
      "tone": "Formal ('Sie'), factual and concise. Avoid hype and exaggeration."}
FR = {"code": "fr", "lang": "fr", "language": "French", "spelling": "", "formality": "formal-polite",
      "tone": "Formal ('vous'), polite and well structured."}
ES = {"code": "es", "lang": "es", "language": "Spanish", "spelling": "", "formality": "formal-warm",
      "tone": "Formal ('usted'), warm and courteous."}

COUNTRY_MAP = {
    **dict.fromkeys(["united states", "canada"], EN_US),
    **dict.fromkeys(["united kingdom", "ireland"], EN_GB),
    **dict.fromkeys(["australia", "new zealand"], EN_AU),
    **dict.fromkeys(["india", "pakistan", "bangladesh", "sri lanka", "nepal"], EN_IN),
    **dict.fromkeys(["united arab emirates", "saudi arabia", "qatar", "kuwait", "bahrain", "oman"], EN_ME),
    **dict.fromkeys(["germany", "austria", "switzerland"], DE),
    **dict.fromkeys(["france", "belgium", "luxembourg"], FR),
    **dict.fromkeys(["spain", "mexico", "argentina", "colombia", "chile", "peru"], ES),
}


def profile_for(country):
    return dict(COUNTRY_MAP.get((country or "").strip().lower(), EN_INT))
