"""Shipping-only error pages retain their own navigation and escape failures."""
from pathlib import Path
import unittest
from jinja2 import Environment, DictLoader
class ShippingErrorPresentation(unittest.TestCase):
    def render_error(self, shipping=True, error="package changed; reload"):
        root=Path(__file__).resolve().parents[1]
        env=Environment(loader=DictLoader({
            "base.html":"{% block content %}{% endblock %}",
            "pilot":(root/"templates/marketplace_pilot.html").read_text()
        }),autoescape=True)
        env.globals.update(community_token=lambda:"fixture",url_for=lambda endpoint,**kwargs:"/"+endpoint)
        return env.get_template("pilot").render(view="error",error=error,shipping_settings_only=shipping)
    def test_shipping_error_stays_in_settings(self):
        text=self.render_error()
        self.assertIn("<h1>Shipping settings</h1>",text)
        self.assertIn("Return to shipping settings",text)
        for label in ("Purchase rehearsal","Your orders","Seller orders","Test catalog","retrying a payment"):
            self.assertNotIn(label,text)
    def test_full_pilot_keeps_order_guidance(self):
        text=self.render_error(False)
        self.assertIn("Purchase rehearsal",text)
        self.assertIn("Your orders",text)
        self.assertIn("retrying a payment",text)
    def test_error_text_is_escaped(self):
        text=self.render_error(error="<img src=x onerror=alert(1)>")
        self.assertNotIn("<img",text)
        self.assertIn("&lt;img",text)
if __name__=="__main__":unittest.main()
