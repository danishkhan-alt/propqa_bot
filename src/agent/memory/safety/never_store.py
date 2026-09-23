"""Things we never keep in memory: secrets, SQL, sensitive topics, other people's prefs.

These are block lists. Before the bot saves a memory, it looks for these kinds of things and refuses them.

- Email, phone, Emirates ID — personal contact / ID details  
- SQL-looking text — database commands or table-ish names  
- Sensitive topics — religion, health, passport, exact salary/income  
- Other people’s preferences — “my wife prefers…”, “their budget…”

So the bot can remember “I want 2 bedrooms under 2M,” 
but not your phone number, your faith, or what your friend wants.
"""

from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(
    r"(?:\+971|00971|0)[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{4}\b|\b\d{3}[-.]\d{3}[-.]\d{4}\b"
)
EMIRATES_ID = re.compile(r"\b784[-\s]?\d{4}[-\s]?\d{7}[-\s]?\d\b")
SQL = re.compile(
    r"\b(select\s+.+\s+from|insert\s+into|delete\s+from|drop\s+table|union\s+select)\b",
    re.IGNORECASE,
)
DOTTED = re.compile(r"\b[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\b", re.IGNORECASE)
PROTECTED = re.compile(
    r"\b(nationality|religion|muslim|christian|hindu|jewish|buddhist|cancer|diabetes|"
    r"hiv|pregnant|passport|emirates id|salary|my income|exact income)\b",
    re.IGNORECASE,
)
THIRD_PARTY = re.compile(
    r"\b(my (?:wife|husband|son|daughter|mother|father|friend|colleague)|"
    r"he prefers|she prefers|their budget)\b",
    re.IGNORECASE,
)
