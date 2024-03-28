# -*- coding: utf-8 -*-

import logging
from django.conf import settings
from datetime import datetime
from django.core.cache import cache
from opaque_keys.edx.keys import CourseKey, UsageKey, LearningContextKey
from opaque_keys import InvalidKeyError
from django.contrib.auth.models import User
from collections import OrderedDict, defaultdict, deque

from celery import current_task, task
from lms.djangoapps.instructor_task.tasks_base import BaseInstructorTask
from lms.djangoapps.instructor_task.api_helper import submit_task
from functools import partial
from time import time
from lms.djangoapps.instructor_task.tasks_helper.runner import run_main_task, TaskProgress
from django.db import IntegrityError, transaction
from django.utils.translation import ugettext_noop
from pytz import UTC
from .utils import get_all_persistant_grades, get_course_grade_summary, get_completion_course

logger = logging.getLogger(__name__)

LIMIT_STUDENTS = 10000
TIME_CACHE  = 300

if hasattr(settings, 'EOL_INSTRUCTOR_TIME_CACHE'):
    TIME_CACHE = settings.EOL_INSTRUCTOR_TIME_CACHE 

@task(base=BaseInstructorTask, queue='edx.lms.core.low')
def process_eolgrades(entry_id, xmodule_instance_args):
    action_name = ugettext_noop('generated')
    task_fn = partial(task_get_eolgrades, xmodule_instance_args)

    return run_main_task(entry_id, task_fn, action_name)


def task_get_eolgrades(
        _xmodule_instance_args,
        _entry_id,
        course_id,
        task_input,
        action_name):
    course_key = course_id
    start_time = time()
    start_date = datetime.now(UTC)
    task_progress = TaskProgress(
        action_name,
        1,
        start_time)
    
    username = task_input["username"]
    user = User.objects.get(username=username)
    data = {
        'details': get_all_persistant_grades(user, course_key),
        'summary': get_course_grade_summary(user, course_key)
    }

    times = datetime.now()
    times = times.strftime("%d/%m/%Y, %H:%M:%S")
    data['time'] = times
    data['time_queue'] = str(TIME_CACHE / 60)
    current_step = {'step': 'Uploading Data Eol Grades'}
    cache.set(
        "eol_grades-" +
        str(course_id) +
        "-data",
        data,
        TIME_CACHE)

    return task_progress.update_task_state(extra_meta=current_step)


def task_process_eolgrades(request, course_id):
    course_key = CourseKey.from_string(course_id)
    task_type = 'EOL_Instructor_Grades'
    task_class = process_eolgrades
    task_input = {'username': request.user.username}
    task_key = course_id

    return submit_task(
        request,
        task_type,
        task_class,
        course_key,
        task_input,
        task_key)

@task(base=BaseInstructorTask, queue='edx.lms.core.low')
def process_eolcompletion(entry_id, xmodule_instance_args):
    action_name = ugettext_noop('generated')
    task_fn = partial(task_get_eolcompletion, xmodule_instance_args)

    return run_main_task(entry_id, task_fn, action_name)


def task_get_eolcompletion(
        _xmodule_instance_args,
        _entry_id,
        course_id,
        task_input,
        action_name):
    course_key = course_id
    start_time = time()
    start_date = datetime.now(UTC)
    task_progress = TaskProgress(
        action_name,
        1,
        start_time)
    
    data = get_completion_course(course_key)
    times = datetime.now()
    times = times.strftime("%d/%m/%Y, %H:%M:%S")
    data['time'] = times
    data['time_queue'] = str(TIME_CACHE / 60)
    current_step = {'step': 'Uploading Data Eol Completion'}
    cache.set(
        "eol_completion_instructor-" +
        str(course_id) +
        "-data",
        data,
        TIME_CACHE)

    return task_progress.update_task_state(extra_meta=current_step)

def task_process_eolcompletion(request, course_id):
    course_key = CourseKey.from_string(course_id)
    task_type = 'EOL_Instructor_Completion'
    task_class = process_eolcompletion
    task_input = {}
    task_key = course_id

    return submit_task(
        request,
        task_type,
        task_class,
        course_key,
        task_input,
        task_key)