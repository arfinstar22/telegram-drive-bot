"""Tests for Darfin Storage Logo and Favicon Integration."""

import unittest
from pathlib import Path
import tornado.testing
import tornado.web

import webapp


class TestLogoAssetsServing(tornado.testing.AsyncHTTPTestCase):
    """Test static endpoints serving the cropped Darfin logo and favicons."""

    def get_app(self):
        routes = webapp.build_app_routes()
        return tornado.web.Application(routes)

    def test_favicon_ico_served(self):
        resp = self.fetch("/favicon.ico")
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "image/x-icon")
        self.assertTrue(len(resp.body) > 0)

    def test_favicon_png_served(self):
        resp = self.fetch("/favicon.png")
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "image/png")
        self.assertTrue(len(resp.body) > 0)

    def test_darfin_logo_png_served(self):
        resp = self.fetch("/static/darfin_logo.png")
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "image/png")
        self.assertTrue(len(resp.body) > 0)

    def test_apple_touch_icon_served(self):
        resp = self.fetch("/static/apple-touch-icon.png")
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "image/png")
        self.assertTrue(len(resp.body) > 0)


class TestLogoMarkupInTemplates(unittest.TestCase):
    """Verify HTML templates include cropped logo and favicon links without generic placeholders."""

    def test_webapp_template_logo(self):
        with open("templates/webapp.html", "r", encoding="utf-8") as f:
            content = f.read()

        # Favicon tags
        self.assertIn('<link rel="icon" type="image/x-icon" href="/favicon.ico">', content)
        self.assertIn('<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">', content)
        self.assertIn('<link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">', content)

        # Header brand logo uses cropped darfin_logo.png
        self.assertIn('<img src="/static/darfin_logo.png" alt="Darfin Storage Logo"', content)

        # Standalone login card uses cropped darfin_logo.png
        self.assertIn('<img src="/static/darfin_logo.png" alt="DARFIN Logo"', content)

    def test_dropzone_template_logo(self):
        with open("templates/dropzone.html", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('<link rel="icon" type="image/x-icon" href="/favicon.ico">', content)
        self.assertIn('<img src="/static/darfin_logo.png" alt="Darfin Storage Logo"', content)

    def test_share_file_template_logo(self):
        with open("templates/share_file.html", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('<link rel="icon" type="image/x-icon" href="/favicon.ico">', content)
        self.assertIn('<img src="/static/darfin_logo.png" alt="Darfin Storage Logo"', content)


if __name__ == "__main__":
    unittest.main()
