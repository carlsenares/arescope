"""Server-rendered app surface (signup / login / dashboard / new scan).

Kept deliberately framework-light: FastAPI + Jinja templates that reuse the
marketing site's design tokens, so the whole product is one origin and one
look without a second frontend stack.
"""
