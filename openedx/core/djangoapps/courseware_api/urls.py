"""
Contains all the URLs
"""


from django.conf import settings
from django.conf.urls import url

from openedx.core.djangoapps.courseware_api import views

urlpatterns = [
    url(r'^course/{}'.format(settings.COURSE_KEY_PATTERN),
        views.CoursewareInformation.as_view(),
        name="course-detail-v2"),
]
