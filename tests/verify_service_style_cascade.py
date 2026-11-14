"""Regress the actual shared-settings/Service selector collision, without a browser.

This checks CSS cascade declarations, not layout, hover, focus or visual acceptance.
Run with requirements-ui-checks.txt and the app's existing Jinja dependency.
"""
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
import cssselect2
import tinycss2
from jinja2 import Environment, DictLoader

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / 'templates/service_accounts.html').read_text()
SHARED = (ROOT / 'static/css/media.css').read_text()


class DOM(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.root = ET.Element('html')
        self.stack = [self.root]
        self.styles = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = ET.SubElement(self.stack[-1], tag, {k:v or '' for k,v in attrs})
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        if self.stack[-1].tag == 'style':
            self.styles.append(data)


def render(view, populated=True, error=None, template=SERVICE):
    env = Environment(loader=DictLoader({'base.html':'<div id="main-content">{% block content %}{% endblock %}</div>','service.html':template}), autoescape=True)
    env.globals['url_for'] = lambda endpoint, **kw: '/' + endpoint
    item = dict(handle='@StyleFixture',purpose='Fictional styling fixture only.',enabled=True,owner_id=1,user_id=5,revision=1)
    return DOM(env.get_template('service.html').render(view=view,services=[item] if populated else [],service=item,operators={5:[]},events=[],error=error,token='fixture',request_key='fixture',request=SimpleNamespace(form={})))


def declarations(dom):
    matcher = cssselect2.Matcher()
    for source in [SHARED, *dom.styles]:
        for rule in tinycss2.parse_stylesheet(source, skip_whitespace=True, skip_comments=True):
            if rule.type != 'qualified-rule':
                continue  # Responsive/forced-colors and dynamic states need browser review.
            if '::' in tinycss2.serialize(rule.prelude):
                continue  # Pseudo-elements are not the button elements under test.
            parsed = tinycss2.parse_declaration_list(rule.content, skip_whitespace=True, skip_comments=True)
            values = [(d.lower_name,tinycss2.serialize(d.value).strip(),d.important) for d in parsed if d.type=='declaration']
            for selector in cssselect2.compile_selector_list(tinycss2.serialize(rule.prelude)):
                matcher.add_selector(selector, values)
    result = []
    for node in cssselect2.ElementWrapper.from_html_root(dom.root).iter_subtree():
        if node.etree_element.tag != 'button':
            continue
        cascade = {}
        for specificity, order, pseudo, values in matcher.match(node):
            if pseudo is not None:
                continue
            for name,value,important in values:
                rank = (important,specificity,order)
                if name not in cascade or rank >= cascade[name][0]:
                    cascade[name] = (rank,value)
        result.append({k:v[1] for k,v in cascade.items()})
    return result


class ServiceCascadeTests(unittest.TestCase):
    def test_all_rendered_service_buttons_keep_contrast_palette_and_touch_minimum(self):
        for view in ['compose','manage']:
            with self.subTest(view=view):
                buttons = declarations(render(view))
                self.assertTrue(buttons)
                for style in buttons:
                    self.assertEqual(style['min-height'],'44px')
                    self.assertEqual(style['background'],'#c1e6ff')
                    self.assertEqual(style['color'],'#102239')

    def test_previous_selector_reproduces_observed_shared_css_regression(self):
        previous = SERVICE.replace('.community-page.service-workspace','.service-workspace')
        style = declarations(render('compose',template=previous))[0]
        self.assertEqual((style['min-height'],style['background'],style['color']),('34px','#4e9ddc','#fff'))

    def test_other_settings_pages_retain_shared_styling(self):
        dom = DOM('<div id="main-content"><main class="community-page"><button>Other settings</button></main></div>')
        dom.styles = render('compose').styles
        style = declarations(dom)[0]
        self.assertEqual((style['min-height'],style['background'],style['color']),('34px','#4e9ddc','#fff'))

    def test_list_empty_and_error_views_render_scoped_styles(self):
        for populated,error in [(True,None),(False,None),(False,'Fictional error')]:
            dom = render('mine',populated,error)
            self.assertTrue(dom.styles)
            self.assertTrue(any('service-workspace' in n.attrib.get('class','') for n in dom.root.iter()))


if __name__ == '__main__':
    unittest.main()
