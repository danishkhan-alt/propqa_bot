FOLLOW_UP_KIND_SYSTEM = """Classify this follow-up against the current query frame. Do not answer the user.

kind is one of:
- refine: same search, with a change to filters, sort, projection, or a row reference
- pivot: same place or property, different subject
- new: unrelated request
"""
