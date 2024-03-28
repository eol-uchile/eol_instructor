from django.contrib import admin
from django.conf.urls import url
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from .views import *

urlpatterns = [
    url(
        r'eol_instructor/grades_data/{}$'.format(
            settings.COURSE_ID_PATTERN,
        ),
        EolGrades.as_view(),
        name='get_grades',
    ),
    url(
        r'eol_instructor/user_info/(?P<username>[-_a-zA-Z0-9]+)/{}$'.format(
            settings.COURSE_ID_PATTERN,
        ),
        get_user_info_api,
        name='get_user_info_api',
    ),
    url(
        r'eol_instructor/completion_data/{}$'.format(
            settings.COURSE_ID_PATTERN,
        ),
        EolCompletionInstructor.as_view(),
        name='get_completion_data',
    ),
]
