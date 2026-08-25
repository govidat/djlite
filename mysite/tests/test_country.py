"""
Tests for the Country feature:
  - Country model CRUD + uniqueness
  - Client allowed_countries / default_country_code
  - set_country session view
  - Middleware country resolution
  - Template resolution with country dimension
"""
from django.test import TestCase, RequestFactory
from django.contrib.sessions.backends.db import SessionStore
from django.urls import reverse

from mysite.models.global_config import Country
from mysite.models.client import Client, SectorTemplate, ClientTemplate
from mysite.models import Taxonomy, TaxonomyNode


def _ensure_country(code, name='Test Country', flag='🏳️', order=99):
    c, _ = Country.objects.get_or_create(
        code=code, defaults={'name': name, 'flag_emoji': flag, 'order': order}
    )
    return c


class CountryModelTest(TestCase):
    """Test Country model basics."""

    def test_create_country(self):
        c = _ensure_country('ZA', name='South Africa', flag='🇿🇦', order=10)
        self.assertEqual(c.code, 'ZA')
        self.assertEqual(c.name, 'South Africa')
        self.assertTrue(c.is_active)

    def test_country_str(self):
        c = _ensure_country('BR', name='Brazil', flag='🇧🇷')
        self.assertEqual(str(c), '🇧🇷 BR - Brazil')

    def test_country_ordering(self):
        _ensure_country('US', name='USA', order=2)
        _ensure_country('IN', name='India', order=1)
        codes = list(Country.objects.filter(code__in=['IN', 'US']).values_list('code', flat=True).order_by('order'))
        self.assertEqual(codes, ['IN', 'US'])

    def test_country_primary_key_is_code(self):
        c = _ensure_country('JP', name='Japan')
        self.assertEqual(c.pk, 'JP')
        retrieved = Country.objects.get(pk='JP')
        self.assertEqual(retrieved.name, 'Japan')

    def test_unique_constraint_on_code(self):
        _ensure_country('NG', name='Nigeria')
        with self.assertRaises(Exception):
            Country.objects.create(code='NG', name='Duplicate')


class ClientCountryFieldsTest(TestCase):
    """Test Client country-related fields and helpers."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            client_id='testclient',
            name='Test Client',
            allowed_countries=['IN', 'US'],
            default_country_code='IN',
        )

    def test_is_country_enabled_true(self):
        self.assertTrue(self.client_obj.is_country_enabled())

    def test_is_country_enabled_null(self):
        c = Client.objects.create(client_id='no_country', name='No Country')
        self.assertFalse(c.is_country_enabled())

    def test_get_allowed_country_codes(self):
        codes = self.client_obj.get_allowed_country_codes()
        self.assertEqual(codes, {'IN', 'US'})

    def test_get_allowed_country_codes_raises_when_disabled(self):
        c = Client.objects.create(client_id='no_country2', name='No Country 2')
        with self.assertRaises(ValueError):
            c.get_allowed_country_codes()

    def test_default_country_code(self):
        self.assertEqual(self.client_obj.default_country_code, 'IN')


class SetCountryViewTest(TestCase):
    """Test the set_country POST view."""

    def setUp(self):
        self.factory = RequestFactory()
        self.url = reverse('set_country')
        self.client_obj = Client.objects.create(
            client_id='testclient',
            allowed_countries=['IN', 'US', 'FR'],
            default_country_code='IN',
        )
        Country.objects.bulk_create([
            Country(code='IN', name='India', flag_emoji='🇮🇳', order=1),
            Country(code='US', name='USA', flag_emoji='🇺🇸', order=2),
            Country(code='FR', name='France', flag_emoji='🇫🇷', order=3),
        ], ignore_conflicts=True)

    def test_set_valid_country(self):
        request = self.factory.post(self.url, {'country_code': 'US'})
        request.session = SessionStore()
        request.META['HTTP_REFERER'] = '/test/'
        request.client = self.client_obj
        from mysite.views.main import set_country
        response = set_country(request)
        self.assertEqual(request.session['active_country_code'], 'US')
        self.assertEqual(response.status_code, 302)

    def test_set_invalid_country_falls_back_to_default(self):
        request = self.factory.post(self.url, {'country_code': 'XX'})
        request.session = SessionStore()
        request.META['HTTP_REFERER'] = '/test/'
        request.client = self.client_obj
        from mysite.views.main import set_country
        response = set_country(request)
        self.assertEqual(request.session['active_country_code'], 'IN')

    def test_set_country_without_client(self):
        request = self.factory.post(self.url, {'country_code': 'US'})
        request.session = SessionStore()
        request.META['HTTP_REFERER'] = '/test/'
        request.client = None
        from mysite.views.main import set_country
        response = set_country(request)
        self.assertNotIn('active_country_code', request.session)


class TemplateResolutionCountryTest(TestCase):
    """Test _resolve_template_html with country dimension."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            client_id='templclient',
            name='Template Client',
            allowed_countries=['IN', 'US'],
            default_country_code='IN',
        )
        # Global default (no country)
        self.global_default = SectorTemplate.objects.create(
            template_key='footer_v001',
            htmlblob='<footer>GLOBAL DEFAULT</footer>',
            is_active=True,
        )

    def test_global_default_no_country(self):
        from mysite.templatetags.my_tags import _resolve_template_html
        result = _resolve_template_html('templclient', 'footer_v001')
        self.assertEqual(result, '<footer>GLOBAL DEFAULT</footer>')

    def test_global_default_with_country_no_override(self):
        from mysite.templatetags.my_tags import _resolve_template_html
        result = _resolve_template_html('templclient', 'footer_v001', country_code='IN')
        self.assertEqual(result, '<footer>GLOBAL DEFAULT</footer>')

    def test_country_specific_overrides_global(self):
        _ensure_country('IN', name='India', flag='🇮🇳')
        SectorTemplate.objects.create(
            template_key='footer_v001',
            country=Country.objects.get(code='IN'),
            htmlblob='<footer>INDIA FOOTER</footer>',
            is_active=True,
        )
        from mysite.templatetags.my_tags import _resolve_template_html
        result = _resolve_template_html('templclient', 'footer_v001', country_code='IN')
        self.assertEqual(result, '<footer>INDIA FOOTER</footer>')

    def test_other_country_still_gets_global(self):
        _ensure_country('US', name='USA', flag='🇺🇸')
        _ensure_country('IN', name='India', flag='🇮🇳')
        SectorTemplate.objects.create(
            template_key='footer_v001',
            country=Country.objects.get(code='IN'),
            htmlblob='<footer>INDIA FOOTER</footer>',
            is_active=True,
        )
        from mysite.templatetags.my_tags import _resolve_template_html
        result = _resolve_template_html('templclient', 'footer_v001', country_code='US')
        self.assertEqual(result, '<footer>GLOBAL DEFAULT</footer>')

    def test_sector_country_overrides_sector_only(self):
        tax = Taxonomy.objects.create(name='Sector', slug='sector')
        sector = TaxonomyNode.objects.create(
            taxonomy=tax, name='AutoComponents', order=1, depth=1,
        )
        self.client_obj.sector = sector
        self.client_obj.save()

        SectorTemplate.objects.create(
            sector_node=sector,
            template_key='footer_v001',
            htmlblob='<footer>SECTOR FOOTER</footer>',
            is_active=True,
        )
        _ensure_country('IN', name='India', flag='🇮🇳')
        SectorTemplate.objects.create(
            sector_node=sector,
            country=Country.objects.get(code='IN'),
            template_key='footer_v001',
            htmlblob='<footer>INDIA SECTOR FOOTER</footer>',
            is_active=True,
        )

        from mysite.templatetags.my_tags import _resolve_template_html
        result = _resolve_template_html('templclient', 'footer_v001', country_code='IN')
        self.assertEqual(result, '<footer>INDIA SECTOR FOOTER</footer>')

    def test_empty_template_key_returns_empty(self):
        from mysite.templatetags.my_tags import _resolve_template_html
        result = _resolve_template_html('templclient', 'nonexistent_key')
        self.assertEqual(result, '')

    def test_client_template_country_overrides_sector_country(self):
        _ensure_country('IN', name='India', flag='🇮🇳')
        SectorTemplate.objects.create(
            template_key='footer_v001',
            country=Country.objects.get(code='IN'),
            htmlblob='<footer>SECTOR COUNTRY FOOTER</footer>',
            is_active=True,
        )
        ClientTemplate.objects.create(
            client=self.client_obj,
            template_key='footer_v001',
            country=Country.objects.get(code='IN'),
            htmlblob='<footer>CLIENT COUNTRY FOOTER</footer>',
            is_active=True,
        )
        from mysite.templatetags.my_tags import _resolve_template_html
        result = _resolve_template_html('templclient', 'footer_v001', country_code='IN')
        self.assertEqual(result, '<footer>CLIENT COUNTRY FOOTER</footer>')
