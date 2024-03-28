#!/bin/dash

pip install -e /openedx/requirements/eol_instructor

cd /openedx/requirements/eol_instructor
cp /openedx/edx-platform/setup.cfg .
mkdir test_root
cd test_root/
ln -s /openedx/staticfiles .

cd /openedx/requirements/eol_instructor

DJANGO_SETTINGS_MODULE=lms.envs.test EDXAPP_TEST_MONGO_HOST=mongodb pytest eol_instructor/tests.py

rm -rf test_root
