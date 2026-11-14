"""Exercise the real Services templates and stylesheets with isolated fixture data."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PEACH = "rgb(252, 181, 163)"
BLUE = "rgb(193, 230, 255)"
INK = "rgb(16, 34, 57)"


def render(path, view, services, error=None):
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    env.globals.update(
        url_for=lambda endpoint, **kw: "/static/" + kw["filename"] if endpoint == "static" else "/" + endpoint,
        can_access_manage=lambda: True, get_flashed_messages=lambda **kw: [],
        media_preferences=dict, atmosphere_preferences=dict,
    )
    return env.get_template("service_accounts.html").render(
        request=SimpleNamespace(path=path, endpoint="services." + view, form={}),
        session=dict(user_id=1, user_email="fixture@example.invalid", user_handle="@fixture"),
        view=view, services=services, service=services[0] if services else None,
        operators={5: [dict(handle="@operator", user_id=2)], 6: []},
        events=[], error=error, age_policy_age=30, search_scope_labels={},
    )


class BrowserStyles(unittest.TestCase):
    def test_service_views(self):
        services = [dict(handle="@Fixture" + str(i), enabled=enabled, user_id=i,
                         owner_id=1, revision=1, purpose="Fixture guidance")
                    for i, enabled in [(5, True), (6, False)]]
        cases = [
            ("/services", "mine", services, None),
            ("/services", "mine", [], "Fixture error"),
            ("/services/5/publish", "compose", services, None),
            ("/manage/services", "manage", services, None),
        ]
        with sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=os.getenv("CHROME_BIN"))
            for width in (1280, 390):
                page = browser.new_page(viewport={"width": width, "height": 844})
                for path, view, rows, error in cases:
                    with self.subTest(width=width, path=path, error=error):
                        html = render(path, view, rows, error)
                        def serve(route):
                            url = urlparse(route.request.url)
                            if url.hostname == "fixture.invalid" and url.path == path:
                                return route.fulfill(content_type="text/html", body=html)
                            if url.hostname == "fixture.invalid" and url.path.startswith("/static/") and url.path.endswith(".css"):
                                return route.fulfill(content_type="text/css", path=ROOT / url.path.lstrip("/"))
                            route.abort()
                        page.route("**/*", serve)
                        try:
                            page.goto("https://fixture.invalid" + path)
                            self.check_view(page, view, rows, error)
                        finally:
                            page.unroute("**/*", serve)
                page.close()
            browser.close()

    def check_view(self, page, view, rows, error):
        panel = page.locator(".service-workspace")
        self.assertEqual(page.locator(".account-workspace-content .service-workspace").count(), int(view == "manage"))
        self.assertEqual(panel.get_by_role("alert").count(), int(bool(error)))
        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        links = panel.get_by_role("link").all()
        buttons = panel.get_by_role("button").all()
        self.assertEqual(len(links), 2 + (2 * len(rows) if view != "compose" else 0))
        if view == "manage":
            self.assertEqual({b.inner_text() for b in buttons}, {
                "Create service with public guidance publishing", "Disable service",
                "Enable service", "Revoke publishing", "Grant public guidance publishing",
            })
        else:
            self.assertEqual(len(buttons), int(view == "compose"))
        for control in links + buttons:
            staff = view == "manage" and control in buttons
            normal = ["rgb(51, 51, 51)", PEACH] if staff else [BLUE, INK]
            hover = [PEACH, "rgb(28, 28, 28)"] if staff else ["rgb(227, 244, 255)", INK]
            page.mouse.move(0, 0)
            expect(control).to_have_css("background-color", normal[0])
            expect(control).to_have_css("color", normal[1])
            self.assertGreaterEqual(control.bounding_box()["height"], 44)
            control.hover()
            expect(control).to_have_css("background-color", hover[0])
            expect(control).to_have_css("color", hover[1])
            control.focus()
            page.keyboard.press("Shift+Tab")
            page.keyboard.press("Tab")
            self.assertTrue(control.evaluate("e => e === document.activeElement && e.matches(':focus-visible')"))
            self.assertEqual(control.evaluate("e => getComputedStyle(e).outline"), "rgb(252, 211, 77) solid 3px")
