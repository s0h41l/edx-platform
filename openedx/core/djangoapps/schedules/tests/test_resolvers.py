"""
Tests for schedules resolvers
"""


import datetime
from unittest import skipUnless

import ddt
from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings
from mock import Mock, patch
from waffle.testutils import override_switch

from openedx.core.djangoapps.schedules.config import COURSE_UPDATE_WAFFLE_FLAG
from openedx.core.djangoapps.schedules.resolvers import (
    BinnedSchedulesBaseResolver,
    CourseUpdateResolver,
)
from openedx.core.djangoapps.schedules.tests.factories import ScheduleConfigFactory
from openedx.core.djangoapps.site_configuration.tests.factories import SiteConfigurationFactory, SiteFactory
from openedx.core.djangoapps.waffle_utils.testutils import override_waffle_flag
from openedx.core.djangolib.testing.utils import CacheIsolationMixin, skip_unless_lms
from student.tests.factories import CourseEnrollmentFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory


class SchedulesResolverTestMixin(CacheIsolationMixin):
    """
    Base class for the resolver tests.
    """
    def setUp(self):
        super(SchedulesResolverTestMixin, self).setUp()
        self.site = SiteFactory.create()
        self.site_config = SiteConfigurationFactory(site=self.site)
        self.schedule_config = ScheduleConfigFactory.create(site=self.site)


@ddt.ddt
@skip_unless_lms
@skipUnless('openedx.core.djangoapps.schedules.apps.SchedulesConfig' in settings.INSTALLED_APPS,
            "Can't test schedules if the app isn't installed")
class TestBinnedSchedulesBaseResolver(SchedulesResolverTestMixin, TestCase):
    """
    Tests the BinnedSchedulesBaseResolver.
    """
    def setUp(self):
        super(TestBinnedSchedulesBaseResolver, self).setUp()

        self.resolver = BinnedSchedulesBaseResolver(
            async_send_task=Mock(name='async_send_task'),
            site=self.site,
            target_datetime=datetime.datetime.now(),
            day_offset=3,
            bin_num=2,
        )

    @ddt.data(
        'course1'
    )
    def test_get_course_org_filter_equal(self, course_org_filter):
        self.site_config.values['course_org_filter'] = course_org_filter
        self.site_config.save()
        mock_query = Mock()
        result = self.resolver.filter_by_org(mock_query)
        self.assertEqual(result, mock_query.filter.return_value)
        mock_query.filter.assert_called_once_with(enrollment__course__org=course_org_filter)

    @ddt.unpack
    @ddt.data(
        (['course1', 'course2'], ['course1', 'course2'])
    )
    def test_get_course_org_filter_include__in(self, course_org_filter, expected_org_list):
        self.site_config.values['course_org_filter'] = course_org_filter
        self.site_config.save()
        mock_query = Mock()
        result = self.resolver.filter_by_org(mock_query)
        self.assertEqual(result, mock_query.filter.return_value)
        mock_query.filter.assert_called_once_with(enrollment__course__org__in=expected_org_list)

    @ddt.unpack
    @ddt.data(
        (None, set([])),
        ('course1', set([u'course1'])),
        (['course1', 'course2'], set([u'course1', u'course2']))
    )
    def test_get_course_org_filter_exclude__in(self, course_org_filter, expected_org_list):
        SiteConfigurationFactory.create(
            values={'course_org_filter': course_org_filter},
        )
        mock_query = Mock()
        result = self.resolver.filter_by_org(mock_query)
        mock_query.exclude.assert_called_once_with(enrollment__course__org__in=expected_org_list)
        self.assertEqual(result, mock_query.exclude.return_value)


@skip_unless_lms
@skipUnless('openedx.core.djangoapps.schedules.apps.SchedulesConfig' in settings.INSTALLED_APPS,
            "Can't test schedules if the app isn't installed")
class TestCourseUpdateResolver(SchedulesResolverTestMixin, ModuleStoreTestCase):
    """
    Tests the CourseUpdateResolver.
    """
    def setUp(self):
        super(TestCourseUpdateResolver, self).setUp()
        self.course = CourseFactory(highlights_enabled_for_messaging=True, self_paced=True)
        with self.store.bulk_operations(self.course.id):
            ItemFactory.create(parent=self.course, category='chapter', highlights=[u'good stuff'])

    def create_resolver(self):
        """
        Creates a CourseUpdateResolver with an enrollment to schedule.
        """
        with patch('openedx.core.djangoapps.schedules.signals.get_current_site') as mock_get_current_site:
            mock_get_current_site.return_value = self.site_config.site
            enrollment = CourseEnrollmentFactory(course_id=self.course.id, user=self.user, mode=u'audit')

        return CourseUpdateResolver(
            async_send_task=Mock(name='async_send_task'),
            site=self.site_config.site,
            target_datetime=enrollment.schedule.start,
            day_offset=-7,
            bin_num=CourseUpdateResolver.bin_num_for_user_id(self.user.id),
        )

    @override_settings(CONTACT_MAILING_ADDRESS='123 Sesame Street')
    @override_waffle_flag(COURSE_UPDATE_WAFFLE_FLAG, True)
    def test_schedule_context(self):
        resolver = self.create_resolver()
        schedules = list(resolver.schedules_for_bin())
        expected_context = {
            'contact_email': 'info@example.com',
            'contact_mailing_address': '123 Sesame Street',
            'course_ids': [str(self.course.id)],
            'course_name': self.course.display_name,
            'course_url': '/courses/{}/course/'.format(self.course.id),
            'dashboard_url': '/dashboard',
            'homepage_url': '/',
            'mobile_store_urls': {},
            'platform_name': u'\xe9dX',
            'show_upsell': False,
            'social_media_urls': {},
            'template_revision': 'release',
            'unsubscribe_url': None,
            'week_highlights': ['good stuff'],
            'week_num': 1,
        }
        self.assertEqual(schedules, [(self.user, None, expected_context, True)])

    @override_waffle_flag(COURSE_UPDATE_WAFFLE_FLAG, True)
    @override_switch('schedules.course_update_show_unsubscribe', True)
    def test_schedule_context_show_unsubscribe(self):
        resolver = self.create_resolver()
        schedules = list(resolver.schedules_for_bin())
        self.assertIn('optout', schedules[0][2]['unsubscribe_url'])
