import asyncio
from playwright.async_api import async_playwright

import os

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:5173")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        results = []

        def check(label, condition):
            results.append((label, bool(condition)))
            print(("PASS" if condition else "FAIL"), "-", label)

        await page.goto(BASE)
        await page.wait_for_selector("h1")
        check("Login screen shown when logged out", "Sign in" in (await page.text_content("body")))

        await page.fill("#login-username", "admin")
        await page.fill("#login-password", "changeme123")
        await page.click("button:has-text('Sign in')")
        await page.wait_for_selector(".top-level-tabs", timeout=10000)
        check("App loads with title", await page.text_content("h1") == "AI Quality Engineering Copilot")
        check("User badge shows logged-in username", "admin" in (await page.text_content(".user-badge")))

        # Mode pill should say mock mode since no API key configured
        mode_text = await page.text_content(".mode-pill")
        check("Mode pill shows mock mode", "Mock mode" in mode_text)

        # Second pill: embedding tier (llm/local/mock) — whichever the server
        # actually resolved to, just confirm it rendered something real.
        embedding_pill_texts = await page.locator(".mode-pill").all_text_contents()
        embedding_pill = next((t for t in embedding_pill_texts if "embeddings:" in t), "")
        check(
            "Embedding-mode pill shows a resolved tier",
            any(s in embedding_pill for s in ("OpenAI", "local model", "hashed (offline)")),
        )

        # ---- Generate tab: paste text flow ----
        await page.click("text=Use sample requirement")
        await page.click("button:has-text('Generate test cases')")
        await page.wait_for_selector(".test-case-table", timeout=10000)
        rows = await page.locator(".test-case-table tbody tr").count()
        check("Paste-text generation returns 5 rows", rows == 5)

        # Save to library
        await page.click("button:has-text('Save to library')")
        await page.wait_for_selector(".success-banner", timeout=10000)
        success_text = await page.text_content(".success-banner")
        check("Save to library shows success message", "Saved 5" in success_text)

        # ---- Generate tab: documents + RAG flow ----
        await page.click("text=Generate from uploaded documents")
        await page.wait_for_selector("input[type=file]", state="attached", timeout=5000)
        async with page.expect_response(lambda r: "/api/v1/documents" in r.url and r.request.method == "POST", timeout=20000) as resp_info:
            await page.set_input_files("input[type=file]", os.path.join(REPO_ROOT, "sample-data", "sample_requirement.txt"))
        upload_resp = await resp_info.value
        check("Document upload POST returns 200", upload_resp.status == 200)
        await page.wait_for_selector(".document-list li", timeout=20000)
        doc_count = await page.locator(".document-list li").count()
        check("Document uploaded and listed", doc_count >= 1)

        await page.fill("#rag-query", "member ID length validation")
        await page.click("button:has-text('Retrieve & generate test cases')")
        await page.wait_for_selector(".retrieved-chunks-panel", timeout=10000)
        chunk_count = await page.locator(".retrieved-chunks-panel li").count()
        check("RAG retrieval shows retrieved chunks", chunk_count >= 1)
        rag_rows = await page.locator(".test-case-table tbody tr").count()
        check("RAG generation returns test cases", rag_rows == 5)

        # ---- Library tab ----
        await page.click("nav.top-level-tabs >> text=Library")
        await page.wait_for_selector(".library-panel tbody tr", timeout=10000)
        lib_rows = await page.locator(".library-panel tbody tr").count()
        check("Library shows saved test cases", lib_rows >= 5)

        # Approve the first one
        await page.click(".library-panel tbody tr >> nth=0 >> button:has-text('Approve')")
        await page.wait_for_timeout(500)
        first_status = await page.text_content(".library-panel tbody tr >> nth=0 >> .status-pill")
        check("Approve button updates status pill", first_status.strip() == "approved")

        # ---- Traceability tab ----
        await page.click("nav.top-level-tabs >> text=Traceability Matrix")
        await page.wait_for_selector(".traceability-panel tbody tr", timeout=10000)
        trace_rows = await page.locator(".traceability-panel tbody tr").count()
        check("Traceability matrix shows requirement rows", trace_rows >= 1)

        # ---- Analysis tab ----
        await page.click("nav.top-level-tabs >> text=Duplicate/Conflict Analysis")
        await page.wait_for_selector(".analysis-panel", timeout=10000)
        analysis_text = await page.text_content(".analysis-panel")
        check("Analysis panel renders", "Duplicate" in analysis_text)

        # ---- API Tests (OpenAPI) tab ----
        await page.click("nav.top-level-tabs >> text=API Tests (OpenAPI)")
        await page.wait_for_selector(".openapi-panel", timeout=10000)
        await page.set_input_files(".openapi-panel input[type=file]", os.path.join(REPO_ROOT, "sample-data", "sample_openapi.yaml"))
        await page.wait_for_selector(".endpoint-list li", timeout=10000)
        endpoint_count = await page.locator(".endpoint-list li").count()
        check("OpenAPI spec uploaded and endpoints listed", endpoint_count >= 1)

        await page.click(".openapi-panel button:has-text('Generate API test cases')")
        await page.wait_for_selector(".openapi-panel .test-case-table", timeout=10000)
        api_rows = await page.locator(".openapi-panel .test-case-table tbody tr").count()
        check("API test cases generated from OpenAPI spec", api_rows >= 3)

        # ---- SQL Validations tab ----
        await page.click("nav.top-level-tabs >> text=SQL Validations")
        await page.wait_for_selector(".sql-validation-panel", timeout=10000)
        await page.fill("#sql-req-text", "Member ID search shall accept alphanumeric IDs between 8 and 12 characters.")
        await page.fill("#sql-table", "patients")
        await page.click("button:has-text('Generate SQL validation queries')")
        await page.wait_for_selector(".sql-card", timeout=10000)
        sql_text = await page.text_content(".sql-card .sql-code")
        check("SQL validation query generated and contains SELECT", "SELECT" in sql_text)

        # ---- Users tab (admin-only) ----
        await page.click("nav.top-level-tabs >> text=Users")
        await page.wait_for_selector(".users-panel", timeout=10000)
        await page.fill("#new-username", "e2e_created_user")
        await page.fill("#new-password", "e2e-password-123")
        await page.click("button:has-text('Create user')")
        await page.wait_for_timeout(1000)
        users_text = await page.text_content(".users-panel")
        check("Newly created user appears in users list", "e2e_created_user" in users_text)

        # ---- Usage tab (admin-only) ----
        await page.click("nav.top-level-tabs >> text=Usage")
        await page.wait_for_selector(".usage-panel", timeout=10000)
        usage_text = await page.text_content(".usage-panel")
        check("Usage panel shows total calls stat", "total calls" in usage_text)

        # ---- Sign out ----
        await page.click("button:has-text('Sign out')")
        await page.wait_for_selector("#login-username", timeout=10000)
        check("Signing out returns to login screen", "Sign in" in (await page.text_content("body")))

        await browser.close()

        print()
        failed = [label for label, ok in results if not ok]
        if failed:
            print(f"{len(failed)} CHECK(S) FAILED:", failed)
            raise SystemExit(1)
        print(f"All {len(results)} checks passed.")


asyncio.run(main())
