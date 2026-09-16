"""Deterministic visual QA comparison for a Figma export and live URL."""
from __future__ import annotations

import io
import re
from typing import List, Optional

from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from backend.models.schemas import VisualCheck, VisualCompareResponse


def _tokens(value: str) -> List[str]:
    return [item.strip() for item in value.splitlines() if item.strip()]


def _check_text(body_text: str, values: str) -> List[VisualCheck]:
    checks = []
    for expected in _tokens(values):
        present = expected.casefold() in body_text.casefold()
        checks.append(
            VisualCheck(
                category="text",
                label=f"Text: {expected}",
                status="pass" if present else "fail",
                expected=expected,
                actual=expected if present else None,
                detail="Text was found in the live page." if present else "Expected text was not found in the live page.",
            )
        )
    return checks


def _check_numbers(body_text: str, values: str) -> List[VisualCheck]:
    checks = []
    for expected in _tokens(values):
        present = expected in body_text
        checks.append(
            VisualCheck(
                category="numbers",
                label=f"Number: {expected}",
                status="pass" if present else "fail",
                expected=expected,
                actual=expected if present else None,
                detail="Expected numeric value was found." if present else "Expected numeric value was not found.",
            )
        )
    return checks


def compare_visual_reference(
    reference_bytes: bytes,
    url: str,
    viewport_width: int,
    viewport_height: int,
    expected_text: str = "",
    numeric_values: str = "",
    flyout_selector: Optional[str] = None,
    expected_flyout_text: Optional[str] = None,
    pagination_selector: Optional[str] = None,
    expected_page: Optional[str] = None,
) -> VisualCompareResponse:
    reference = Image.open(io.BytesIO(reference_bytes)).convert("RGB")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height}, device_scale_factor=1)
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(500)
            screenshot = Image.open(io.BytesIO(page.screenshot(full_page=False))).convert("RGB")
            body_text = page.locator("body").inner_text(timeout=5000)
            checks = _check_text(body_text, expected_text) + _check_numbers(body_text, numeric_values)

            if flyout_selector:
                try:
                    flyout = page.locator(flyout_selector).first
                    actual = flyout.inner_text(timeout=3000)
                    visible = flyout.is_visible()
                    expected = expected_flyout_text or "visible"
                    matches = visible and (not expected_flyout_text or expected_flyout_text.casefold() in actual.casefold())
                    checks.append(VisualCheck(category="flyout", label=f"Flyout: {flyout_selector}", status="pass" if matches else "fail", expected=expected, actual=actual[:300], detail="Flyout selector is visible and matches the expected content." if matches else "Flyout visibility or content does not match."))
                except PlaywrightTimeoutError:
                    checks.append(VisualCheck(category="flyout", label=f"Flyout: {flyout_selector}", status="fail", expected=expected_flyout_text or "visible", detail="Flyout selector was not found or did not become available."))

            if pagination_selector:
                try:
                    pagination = page.locator(pagination_selector).first.inner_text(timeout=3000)
                    matches = not expected_page or expected_page.casefold() in pagination.casefold()
                    checks.append(VisualCheck(category="pagination", label=f"Pagination: {pagination_selector}", status="pass" if matches else "fail", expected=expected_page or "present", actual=pagination[:300], detail="Pagination state matches the expected page." if matches else "Pagination was found but the expected page was not present."))
                except PlaywrightTimeoutError:
                    checks.append(VisualCheck(category="pagination", label=f"Pagination: {pagination_selector}", status="fail", expected=expected_page or "present", detail="Pagination selector was not found."))
        finally:
            browser.close()

    width = min(reference.width, screenshot.width)
    height = min(reference.height, screenshot.height)
    reference_crop = reference.crop((0, 0, width, height)).resize((width, height))
    screenshot_crop = screenshot.crop((0, 0, width, height))
    difference = ImageChops.difference(reference_crop, screenshot_crop)
    mean_difference = sum(ImageStat.Stat(difference).mean) / 3 / 255 * 100

    checks.insert(0, VisualCheck(category="viewport", label="Viewport dimensions", status="pass" if reference.size == (viewport_width, viewport_height) else "warning", expected=f"{viewport_width}x{viewport_height}", actual=f"reference {reference.width}x{reference.height}; live {screenshot.width}x{screenshot.height}", detail="Reference matches the requested viewport." if reference.size == (viewport_width, viewport_height) else "Reference and live viewport dimensions differ; pixel comparison uses the shared top-left area."))
    return VisualCompareResponse(
        url=url,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        reference_width=reference.width,
        reference_height=reference.height,
        pixel_difference_percent=round(mean_difference, 2),
        checks=checks,
        limitations=["Pixel comparison is a visual signal, not semantic proof.", "Text, numeric, flyout, and pagination checks depend on the selectors/values supplied.", "Figma exports should use the same viewport and pixel density as the live capture."],
    )