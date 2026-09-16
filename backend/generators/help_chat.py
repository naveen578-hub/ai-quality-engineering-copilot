"""Small, offline-safe in-product help assistant."""
from __future__ import annotations

import re

from backend.models.schemas import HelpChatRequest, HelpChatResponse


def answer_help_question(request: HelpChatRequest) -> HelpChatResponse:
    question = request.question.strip().lower()
    if request.surface == "signin":
        if "password" in question or "credential" in question:
            answer = "Use the account provided by your administrator. For a fresh local demo, the seeded account is admin / changeme123; change it before deployment."
            suggestions = ["How do I sign in?", "I forgot my password"]
        elif "role" in question or "permission" in question or "access" in question:
            answer = "Viewer accounts can inspect results, tester accounts can generate and save drafts, and admins can approve, delete, manage users, and view usage."
            suggestions = ["What can a tester do?", "Why is my button disabled?"]
        else:
            answer = "Sign in with your assigned username and password. The app will take you to the Generate workspace after authentication."
            suggestions = ["What do the roles mean?", "I forgot my password"]
        return HelpChatResponse(answer=answer, suggestions=suggestions)

    area = request.active_area or "workspace"
    if any(word in question for word in ("sql", "query", "database", "duplicate")):
        answer = "Open SQL Validations, enter the real table name and explicit column names, then describe the constraint. Generated queries find violations; duplicate checks should return zero rows when values are unique."
        suggestions = ["How do I check a required column?", "Why must I enter a table name?"]
    elif any(word in question for word in ("upload", "document", "rag", "citation")):
        answer = "Use Generate, switch to uploaded documents, upload a supported file, and enter a focused query. Retrieved chunks appear with the generated cases, and citations are tied to stored chunks."
        suggestions = ["What files can I upload?", "How do citations work?"]
    elif any(word in question for word in ("api", "openapi", "swagger", "endpoint")):
        answer = "Open API Tests (OpenAPI), upload a JSON or YAML specification, select endpoints if needed, and generate contract-oriented cases from the documented parameters and responses."
        suggestions = ["How do I upload an OpenAPI file?", "What does an API test cover?"]
    elif "library" in question or "approve" in question or "save" in question:
        answer = "Save generated cases to the Library as drafts. Testers can edit or reject them; only admins can approve or delete saved cases."
        suggestions = ["How do I approve a test case?", "How does traceability work?"]
    elif request.role == "viewer" or "permission" in question or "disabled" in question:
        answer = f"You are currently in the {area} area. Your role is read-only, so generation and write actions stay disabled. Ask an admin to upgrade your role if you need those actions."
        suggestions = ["What can my role do?", "How do I view saved cases?"]
    else:
        answer = f"You are in the {area} area. Ask me about generating cases, documents and citations, API tests, SQL validations, the Library, or role permissions."
        suggestions = ["How do I generate test cases?", "I am stuck on a SQL query"]

    return HelpChatResponse(answer=answer, suggestions=suggestions)