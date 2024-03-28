#!/usr/bin/env python
# -- coding: utf-8 --

import re
import uuid
import json
import logging
import requests
import urllib.parse

from common.djangoapps.student.models import CourseEnrollment, CourseAccessRole
from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponseRedirect, HttpResponseForbidden, Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import ugettext as _
from django.views.generic.base import View
from django.http import HttpResponse
from lms.djangoapps.courseware.access import has_access, get_user_role
from lms.djangoapps.courseware.courses import get_course_by_id, get_course_with_access
from lms.djangoapps.instructor import permissions
from lms.djangoapps.instructor_task.api_helper import AlreadyRunningError
from opaque_keys.edx.keys import CourseKey, UsageKey
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from xmodule.modulestore.django import modulestore
from . import utils
from .tasks import task_process_eolgrades, task_process_eolcompletion
logger = logging.getLogger(__name__)

#####################
#### course info ####
#####################

def get_user_data(course_key):
    """
        Get student enrollment info
    """
    enrolled_users = CourseEnrollment.objects.filter(is_active=1, course_id=course_key).exclude(user__courseaccessrole__course_id=course_key)
    modes = {}
    for x in enrolled_users.values('mode').distinct().order_by():
        modes[x['mode']] = enrolled_users.filter(mode=x['mode']).count()

    staff_users = CourseAccessRole.objects.filter(course_id=course_key).values('user').distinct()
    grades = utils.get_courses_grades(course_key, enrolled_users)
    activity = utils.get_students_activity(course_key, enrolled_users)
    activity_last_week = utils.get_students_activity_last_week(course_key, enrolled_users)
    return {
        'n_team': staff_users.count(),
        'n_student': enrolled_users.count(),
        'n_student_modes': modes,
        'n_passed': grades,
        'activity_started': activity,
        'activity_last_week': activity_last_week
    }

def get_course_data(course_key):
    """
        Get course info
    """
    course = CourseOverview.objects.get(id=course_key)
    return {
        'effort': course.effort,
        'language': course.language,
        'is_self_paced': course.self_paced    
    }

def get_evaluations(course_key, user):
    """
        Get Assignment Types
    """
    from cms.djangoapps.models.settings.course_grading import CourseGradingModel
    with modulestore().bulk_operations(course_key):
        course_details = CourseGradingModel.fetch(course_key)
        from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
        response = CourseGradeFactory().read(user, course_key=course_key)
        data = response.graded_subsections_by_format
        return {
            'n_grades_subsection': {x: len(data[x]) for x in data.keys() },
            'course_details': course_details
            }

def get_course_extra_info(course_key):
    """
       Get extra course info
    """
    n_cert_generated = utils.get_cert_generated(course_key)
    list_xblocks = utils.get_list_xblocks(course_key)
    return {
        'n_cert_generated': n_cert_generated,
        'cohorted': utils.is_course_cohorted(course_key),
        'list_xblocks': list_xblocks,
        'cert_enabled': utils.cert_enabled(course_key)
    }

#####################
###### Grades  ######
#####################

class EolGrades(View):
    @transaction.non_atomic_requests
    def dispatch(self, args, **kwargs):
        return super(EolGrades, self).dispatch(args, **kwargs)

    def get(self, request, course_id, **kwargs):
        course_key = CourseKey.from_string(course_id)
        course = get_course_with_access(request.user, "load", course_key)
        staff_access = bool(has_access(request.user, 'staff', course))
        data_researcher_access = request.user.has_perm(permissions.CAN_RESEARCH, course_key)
        if not (staff_access or data_researcher_access):
            raise Http404()

        context = self.get_context(request, course_id)

        return JsonResponse(context)

    def get_context(self, request, course_id):
        """
            Return eol completion data
        """
        data = cache.get("eol_grades-" + course_id + "-data")
        if data is None:
            data = {"data": False}
            try:
                task_process_eolgrades(request, course_id)
            except AlreadyRunningError:
                pass
        return data

def get_user_info_api(request, username, course_id):
    course_key = CourseKey.from_string(course_id)
    return JsonResponse(utils.get_user_info(username, course_key), safe=False)

#####################
#### Completion  ####
#####################


class EolCompletionInstructor(View):
    @transaction.non_atomic_requests
    def dispatch(self, args, **kwargs):
        return super(EolCompletionInstructor, self).dispatch(args, **kwargs)

    def get(self, request, course_id, **kwargs):
        course_key = CourseKey.from_string(course_id)
        course = get_course_with_access(request.user, "load", course_key)
        staff_access = bool(has_access(request.user, 'staff', course))
        data_researcher_access = request.user.has_perm(permissions.CAN_RESEARCH, course_key)
        if not (staff_access or data_researcher_access):
            raise Http404()

        context = self.get_context(request, course_id)

        return JsonResponse(context)

    def get_context(self, request, course_id):
        """
            Return eol completion data
        """
        data = cache.get("eol_completion_instructor-" + course_id + "-data")
        if data is None:
            data = {"data": False}
            try:
                task_process_eolcompletion(request, course_id)
            except AlreadyRunningError:
                pass
        return data
