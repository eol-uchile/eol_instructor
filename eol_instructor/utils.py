import json
import logging
import requests
import six 
from collections import OrderedDict, defaultdict, deque
from common.djangoapps.student.models import CourseEnrollment
from completion.models import BlockCompletion
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.utils.translation import ugettext as _
from lms.djangoapps.certificates.models import GeneratedCertificate
from lms.djangoapps.courseware.courses import get_course_by_id
from lms.djangoapps.courseware.models import StudentModule
from lms.djangoapps.grades.api import constants as grades_constants
from lms.djangoapps.grades.config import assume_zero_if_absent, should_persist_grades
from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lms.djangoapps.grades.models import PersistentCourseGrade, PersistentSubsectionGrade
from opaque_keys.edx.keys import CourseKey, UsageKey, LearningContextKey
from openedx.core.djangoapps.course_groups.models import CohortMembership, CourseUserGroup
from openedx.core.djangoapps.course_groups import cohorts
from opaque_keys.edx.locator import CourseLocator, BlockUsageLocator
from operator import add
from statistics import mean, pstdev
from lms.djangoapps.certificates import api as certs_api
from xblock.fields import Scope
from xblock_discussion import DiscussionXBlock
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.inheritance import compute_inherited_metadata, own_metadata


logger = logging.getLogger(__name__)
FILTER_LIST = ['xml_attributes']
INHERITED_FILTER_LIST = ['children', 'xml_attributes']

def get_courses_grades(course_key, enrolled_users):
    """
        Get persistent grades
    """
    user_ids = [x['user__id'] for x in enrolled_users.values('user__id')]
    if should_persist_grades(course_key):
        return PersistentCourseGrade.objects.filter(course_id=course_key, user_id__in=user_ids, letter_grade__in=['A','Pass']).count()
    return 0

def get_students_activity(course_key, enrolled_users):
    """
        Get how many student did something in the course
    """
    user_ids = [x['user__id'] for x in enrolled_users.values('user__id')]
    return StudentModule.objects.filter(course_id=course_key, student_id__in=user_ids).values('student_id').distinct().count()

def get_students_activity_last_week(course_key, enrolled_users):
    """
        Get how many student did something in the current week
    """
    user_ids = [x['user__id'] for x in enrolled_users.values('user__id')]
    from datetime import date
    current_week = date.today().isocalendar()[1]
    return StudentModule.objects.filter(course_id=course_key, student_id__in=user_ids, modified__week=current_week).values('student_id').distinct().count()

def get_cert_generated(course_key):
    """
        Get how many cert are generated
    """
    return GeneratedCertificate.objects.filter(
        course_id=course_key, 
        status='downloadable', 
        user__courseenrollment__course_id=course_key, 
        user__courseenrollment__is_active=1).values('user__id').exclude(user__courseaccessrole__course_id=course_key).count()

def get_list_xblocks(course_key):
    """
        Return list advanced modules
    """
    with modulestore().bulk_operations(course_key):
        course_module = modulestore().get_course(course_key)
        return course_module.advanced_modules

def _get_assignment_types(course_key):
    """
    Helper function that returns a serialized dict of assignment types
    for the given course.
    """
    course = get_course_by_id(course_key)
    serialized_grading_policies = {}
    for grader, assignment_type, weight in course.grader.subgraders:
        serialized_grading_policies[assignment_type] = {
            'type': assignment_type,
            'short_label': grader.short_label,
            'min_count': grader.min_count,
            'drop_count': grader.drop_count,
            'weight': weight,
        }
    return serialized_grading_policies

def get_grade_cutoff(course_key):
    """
        Get course grade_cutoffs
    """
    try:
        course = get_course_by_id(course_key)
        grade_cutoff = min(course.grade_cutoffs.values())  # Get the min value
        return grade_cutoff
    except (InvalidKeyError, Http404) as exception:
        error_str = (
            u"Invalid cert: error finding course %s "
            u"Specific error: %s"
        )
        logger.error(error_str, str(course_key), str(exception))
        return None

def get_all_persistant_grades_headers(user, course_key):
    """
        Return grades type
    """
    response = CourseGradeFactory().read(user, course_key=course_key)
    data = response.graded_subsections_by_format
    headers = []
    for grade_type in data.keys(): #Homework, lab, exam
        for inx, usage_key in enumerate(data[grade_type].keys()): #usage_key by grade type
            label = '{} {}'.format(grade_type, (inx + 1))
            headers.append(label)
    return headers

def get_all_persistant_grades(user, course_key):
    """
        Get all user grades
    """
    user_grades = defaultdict(dict)
    enrolled_users = CourseEnrollment.objects.filter(is_active=1, course_id=course_key).exclude(user__courseaccessrole__course_id=course_key).values('user__id', 'user__username')
    user_ids = {x['user__id']:x['user__username'] for x in enrolled_users}
    response = CourseGradeFactory().read(user, course_key=course_key)
    data = response.graded_subsections_by_format
    headers = [{ 'name': 'username', 'data': 'username', 'visible': True }]
    for grade_type in data.keys(): #Homework, lab, exam
        for inx, usage_key in enumerate(data[grade_type].keys()): #usage_key by grade type
            label = '{} {}'.format(grade_type, (inx + 1))
            headers.append({ 'name': label, 'data': label, 'visible': True })
            #TO DO: check override persistant grade
            earned_grades = PersistentSubsectionGrade.objects.filter(course_id=course_key, usage_key=usage_key, user_id__in=user_ids.keys(), first_attempted__isnull=False).values('user_id', 'earned_graded', 'possible_graded', 'first_attempted', 'modified')
            aux_user_graded = [] 
            for x in earned_grades:
                aux_user_graded.append(x['user_id'])
                percent_grade = round_half_up((x['earned_graded']/x['possible_graded'])*100)
                user_grades[x['user_id']][label] = percent_grade
            diff_user_ids = user_ids.keys() - aux_user_graded
            for x in diff_user_ids:
                user_grades[x][label] = 0
    for x in user_grades.keys():
        user_grades[x]['username'] = user_ids[x]
    return {'headers': headers, 'data': list(user_grades.values())}

def is_course_cohorted(course_key):
    """
        Check if course is cohorted 
    """
    return cohorts.is_course_cohorted(course_key)

def cert_enabled(course_key):
    """
        Check if cert is enabled
    """
    certs_api.cert_generation_enabled(course_key)

def get_user_info(username, course_key):
    """
        Return course user info
    """
    user = User.objects.get(username=username)
    enroll_info = CourseEnrollment.objects.get(is_active=1, course_id=course_key, user=user)
    cert_info = GeneratedCertificate.objects.filter(course_id=course_key, status='downloadable', user=user).exists()
    return {
        'fullname': user.profile.name,
        'email': user.email,
        'enroll_date': enroll_info.created,
        'enroll_mode': enroll_info.mode,
        'cert': cert_info,
        'passed': _get_course_grade_passed(user, course_key),
        'grades': user_grade_summary(user, course_key)
    }

def user_grade_summary(user, course_key):
    """
        Get summary of grades user
    """
    #agregar el location de cada subsection
    summary = []
    course = get_course_by_id(course_key)
    course_grade = CourseGradeFactory().read(user, course)
    courseware_summary = list(course_grade.chapter_grades.values())
    for chapter in courseware_summary:
        aux = {'children': []}
        if not chapter['display_name'] == "hidden":
            aux['display_name'] = chapter['display_name']
            for seq in chapter['sections']:
                aux2= {}
                earned = seq.graded_total.earned
                total = seq.graded_total.possible
                percentageString = "{0:.0%}".format(seq.percent_graded) if total > 0 or earned > 0 else ""
                aux2['display_name'] = seq.display_name
                if (total > 0 or earned > 0):
                    aux2['str_score'] = "({0:.3n}/{1:.3n}) {2}".format( float(earned), float(total), percentageString )
                if seq.format is not None:
                    aux2['format'] = seq.format
                if seq.due is not None and not course.self_paced:
                    aux2['due'] = seq.due
                if seq.override is not None:
                    last_override_history = seq.override.get_history().order_by('created').last()
                    if (not last_override_history or last_override_history.system == grades_constants.GradeOverrideFeatureEnum.proctoring) and seq.format == "Exam" and earned == 0:
                        aux2['override'] = _("Suspicious activity detected during proctored exam review. Exam score 0.")
                    else:
                        aux2['override'] = _("Section grade has been overridden.")
                    
                if len(seq.problem_scores.values()) > 0:
                    aux2['graded'] = seq.graded
                    aux2['scores'] = []
                    for score in seq.problem_scores.values():
                        aux2['scores'].append("{0:.3n}/{1:.3n}".format(float(score.earned),float(score.possible)))
                aux['children'].append(aux2)
            summary.append(aux)
    return summary

def _get_course_grade_passed(user, course_key):
    """
        Get 'passed' (Boolean representing whether the course has been
        passed according to the course's grading policy.)
    """
    course_grade = CourseGradeFactory().read(user, course_key=course_key)
    return course_grade.passed

def round_half_up(number):
    return float(Decimal(str(float(number))).quantize(Decimal('0.01'), ROUND_HALF_UP))

def get_header_grades(user, course_key):
    """
        Gets the Grades according to their configuration on grades page
    """
    grades = []
    response = CourseGradeFactory().read(user, course_key=course_key)
    data = response.graded_subsections_by_format
    for grade_type in data.keys():
        for inx, usage_key in enumerate(data[grade_type].keys()):
            label = '{} {}'.format(grade_type, (inx + 1))
            grades.append([label, str(usage_key)])
    return grades

#@lazy
def get_header_grades_sort(user, course_key):
    """
        Gets the Grades according to their release order
    """
    response = CourseGradeFactory().read(user, course_key=course_key)
    subsections = defaultdict(OrderedDict)
    for chapter in six.itervalues(response.chapter_grades):
        for subsection_grade in chapter['sections']:
            if subsection_grade.graded:
                graded_total = subsection_grade.graded_total
                if graded_total.possible > 0:
                    subsections[str(subsection_grade.location)] = subsection_grade.format
    return subsections

def get_course_grade_summary(user, course_key):
    """
        Return a summary grades by block ids
    """
    subsections = get_header_grades_sort(user, course_key)
    grades = OrderedDict()
    enrolled_users = CourseEnrollment.objects.filter(is_active=1, course_id=course_key).exclude(user__courseaccessrole__course_id=course_key).values('user__id')
    user_ids = [x['user__id'] for x in enrolled_users]
    aux_format = {}
    #TO DO: check override persistant grade
    for block_id in subsections.keys():
        usage_key = UsageKey.from_string(block_id)
        grades_range = [0]*21
        subsection_grades = []
        earned_grades = PersistentSubsectionGrade.objects.filter(course_id=course_key, usage_key=usage_key, user_id__in=user_ids, first_attempted__isnull=False).values('user_id', 'earned_graded', 'possible_graded',)
        if subsections[block_id] in aux_format:
            aux_format[subsections[block_id]] = aux_format[subsections[block_id]] + 1
        else:
            aux_format[subsections[block_id]] = 1

        for x in earned_grades:
            percent_grade = round_half_up((x['earned_graded']/x['possible_graded'])*100)
            subsection_grades.append(percent_grade)
            grades_range[int(percent_grade/5)] = grades_range[int(percent_grade/5)] + 1
        grades[block_id] = {
            'grades': subsection_grades,
            'avg': round_half_up(mean(subsection_grades)) if len(subsection_grades) > 0 else 0,
            'grades_range':grades_range,
            'min': min(subsection_grades) if len(subsection_grades) > 0 else 0,
            'max': max(subsection_grades) if len(subsection_grades) > 0 else 0,
            'dev': round_half_up(pstdev(subsection_grades)) if len(subsection_grades) > 0 else 0,
            'len': len(subsection_grades),
            'rate': round_half_up((len(subsection_grades)/len(user_ids))*100),
            'format': "{} {}".format(subsections[block_id], aux_format[subsections[block_id]])
        }
    return grades

#####################
#### Completion  ####
#####################
def get_content(info, id_course):
    """
        Returns dictionary of ordered sections, subsections and units
    """
    max_unit = 0   # Number of units in all sections
    content = OrderedDict()
    children_course = info[id_course]
    children_course = children_course['children']  # All course sections
    children = 0  # Number of units per section
    for id_section in children_course:  # Iterate each section
        section = info[id_section]
        aux_name_sec = section['metadata']
        children = 0
        content[id_section] = {
            'type': 'section',
            'name': aux_name_sec['display_name'],
            'id': id_section,
            'num_children': children}
        subsections = section['children']
        for id_subsection in subsections:  # Iterate each subsection
            subsection = info[id_subsection]
            units = subsection['children']
            aux_name = subsection['metadata']
            len_unit = len(units)
            content[id_subsection] = {
                'type': 'subsection',
                'name': aux_name['display_name'],
                'id': id_subsection,
                'num_children': 0}
            for id_uni in units:  # Iterate each unit and get unit name
                unit = info[id_uni]
                if len(unit['children']) > 0:
                    max_unit += 1
                    content[id_uni] = {
                        'type': 'unit',
                        'name': unit['metadata']['display_name'],
                        'id': id_uni}
                else:
                    len_unit -= 1
            children += len_unit
            content[id_subsection]['num_children'] = len_unit
        content[id_section] = {
            'type': 'section',
            'name': aux_name_sec['display_name'],
            'id': id_section,
            'num_children': children}

    return content, max_unit

def dump_module(
        module,
        destination=None,
        inherited=False,
        defaults=False):
    """
    Add the module and all its children to the destination dictionary in
    as a flat structure.
    """

    destination = destination if destination else {}

    items = own_metadata(module)

    # HACK: add discussion ids to list of items to export (AN-6696)
    if isinstance(
            module,
            DiscussionXBlock) and 'discussion_id' not in items:
        items['discussion_id'] = module.discussion_id

    filtered_metadata = {
        k: v for k,
        v in six.iteritems(items) if k not in FILTER_LIST}

    destination[six.text_type(module.location)] = {
        'category': module.location.block_type,
        'children': [six.text_type(child) for child in getattr(module, 'children', [])],
        'metadata': filtered_metadata,
    }

    if inherited:
        # When calculating inherited metadata, don't include existing
        # locally-defined metadata
        inherited_metadata_filter_list = list(filtered_metadata.keys())
        inherited_metadata_filter_list.extend(INHERITED_FILTER_LIST)

        def is_inherited(field):
            if field.name in inherited_metadata_filter_list:
                return False
            elif field.scope != Scope.settings:
                return False
            elif defaults:
                return True
            else:
                return field.values != field.default

        inherited_metadata = {field.name: field.read_json(
            module) for field in list(module.fields.values()) if is_inherited(field)}
        destination[six.text_type(
            module.location)]['inherited_metadata'] = inherited_metadata

    for child in module.get_children():
        dump_module(child, destination, inherited, defaults)

    return destination

def get_completion_course(course_key):
    """
        Get subsection completeness
    """
    enrolled_students = list(User.objects.filter(
            courseenrollment__course_id=course_key,
            courseenrollment__is_active=1
        ).order_by('username').values('id', 'username', 'email'))
    store = modulestore()
    info = dump_module(store.get_course(course_key))
    id_course = str(BlockUsageLocator(course_key, "course", "course"))
    content, max_unit = get_content(info, id_course)
    data = get_ticks(content, info, enrolled_students, course_key, max_unit)
    return data

def get_header_completion(course_key):
    """
        Get headers to create table head
    """
    store = modulestore()
    info = dump_module(store.get_course(course_key))
    id_course = str(BlockUsageLocator(course_key, "course", "course"))
    content, max_unit = get_content(info, id_course)

    context = {
        "content": content,
        "max_unit": max_unit
    }
    return context

def get_content(info, id_course):
    """
        Returns dictionary of ordered sections, subsections and units
    """
    max_unit = 0   # Number of units in all sections
    content = OrderedDict()
    children_course = info[id_course]['children']
    for id_section in children_course:  # Iterate each section
        section = info[id_section]
        aux_name_sec = section['metadata']
        content[id_section] = {
            'type': 'section',
            'name': aux_name_sec['display_name'],
            'id': id_section,
            'num_children': len(section['children'])}
        for id_subsection in section['children']:  # Iterate each subsection
            subsection = info[id_subsection]
            aux_name = subsection['metadata']
            content[id_subsection] = {
                'type': 'subsection',
                'name': aux_name['display_name'],
                'id': id_subsection,
                'num_children': len(subsection['children'])}
            max_unit += len(subsection['children'])
    return content, max_unit

def get_block(students_id, course_key):
    """
        Get all completed students block
    """
    context_key = LearningContextKey.from_string(str(course_key))
    aux_blocks = BlockCompletion.objects.filter(
        user_id__in=students_id,
        context_key=context_key,
        completion=1.0).values(
        'user_id',
        'block_key')
    blocks = defaultdict(list)
    for b in aux_blocks:
        blocks[b['user_id']].append(str(b['block_key']))

    return blocks

def get_ticks(
        content,
        info,
        enrolled_students,
        course_key,
        max_unit):
    """
        Dictionary of students with ticks if students completed the units
    """
    user_tick = defaultdict(list)
    students_id = []
    students_username = []
    students_email = []
    students_rut = []
    for x in enrolled_students:
        students_id.append(x['id'])
        students_username.append(x['username'])
        students_email.append(x['email'])
        students_rut.append(x['edxloginuser__run'] if 'edxloginuser__run' in x else '')
    certificate = get_certificate(students_id, course_key)
    blocks = get_block(students_id, course_key)
    completion = []
    aux_cert = 0
    for inx, user in enumerate(students_id):
        # Get a list of true/false if they completed the units
        # and number of completed units
        data, aux_completion = get_data_tick(content, info, user, blocks, max_unit)
        aux_user_tick = deque(data)
        aux_user_tick.appendleft(students_rut[inx] if students_rut[inx] != None else '')
        aux_user_tick.appendleft(students_username[inx])
        aux_user_tick.appendleft(students_email[inx])
        aux_user_tick.append('Si' if user in certificate else 'No')
        user_tick['data'].append(list(aux_user_tick))
        if user in certificate:
            aux_cert += 1
        if len(completion) != 0:
            completion = list( map(add, completion, aux_completion) )
        else:
            completion = aux_completion
    completion = [round_half_up(x/len(students_id)) for x in completion]
    completion.append(aux_cert)
    user_tick['completion'] = completion
    if len(students_id) == 0:
        user_tick['data'] = [[True]]
    return user_tick

def get_data_tick(content, info, user_id, blocks, max_unit):
    """
        Get a list of true/false if they completed the units
        and number of completed units
    """
    data = []
    aux_completion = []
    completed_unit = 0  # Number of completed units per student
    completed_unit_per_section = 0  # Number of completed units per section
    num_units_section = 0  # Number of units per section
    section_data = [0,0]
    total_units = [0,0]
    first = True
    for subsection in content.values():
        if subsection['type'] == 'subsection':
            subsection_info = info[subsection['id']]
            blocks_unit = []
            for x in subsection_info['children']:
                blocks_unit = blocks_unit + info[x]['children']
            completed = 0
            for xblock_id in blocks_unit:
                if xblock_id in blocks[user_id] and 'discussion+block' not in xblock_id:
                    completed += 1
            data.append(round_half_up((completed/len(blocks_unit))*100))
            aux_completion.append(round_half_up((completed/len(blocks_unit))*100))
            section_data[0] += completed
            section_data[1] += len(blocks_unit)
            total_units[0] += completed
            total_units[1] += len(blocks_unit)
        if not first and subsection['type'] == 'section' and subsection['num_children'] > 0:
            aux_point = round_half_up((section_data[0]/section_data[1])*100)
            data.append(aux_point)
            aux_completion.append(aux_point)
            section_data = [0,0]
        if first and subsection['type'] == 'section' and subsection['num_children'] > 0:
            first = False
    aux_point = round_half_up((section_data[0]/section_data[1])*100)
    data.append(aux_point)
    aux_completion.append(aux_point)
    aux_final_point = round_half_up((total_units[0]/total_units[1])*100)
    data.append(aux_final_point)
    aux_completion.append(aux_final_point)
    return data, aux_completion

def get_certificate(students_id, course_id):
    """
        Check if users has generated a certificate
    """
    certificates = GeneratedCertificate.objects.filter(status='downloadable',
        user_id__in=students_id, course_id=course_id).values("user_id")
    cer_students_id = [x["user_id"] for x in certificates]

    return cer_students_id
