import unittest
import os
import tempfile

from deploymentutils import render_template, StateConnection, get_dir_of_this_file


"""
These tests can only cover a fraction of the actual features, because the tests do not have access to a remote machine
"""

TEMPLATEDIR = "_test_templates"


class TC1(unittest.TestCase):
    def setUp(self):
        pass

    def test_get_dir_of_this_file(self):
        test_path = get_dir_of_this_file()

        expected_path = os.path.join("deploymentutils", "test")
        self.assertTrue(test_path.endswith(expected_path))

    def test_render_remplate(self):
        test_path = get_dir_of_this_file()
        tmpl_path = os.path.join(test_path, TEMPLATEDIR, "template_1.txt")

        # test creation of target file next to the template
        target_path = os.path.join(test_path, TEMPLATEDIR, "1.txt")
        self.assertFalse(os.path.isfile(target_path))

        res = render_template(tmpl_path, context=dict(abc="test1", xyz=123))
        self.assertTrue(os.path.isfile(target_path))

        # after asserting that the file was created it can be removed
        os.remove(target_path)

        self.assertTrue("test1" in res)
        self.assertTrue("123" in res)

        # - - - -

        # test creation of target file at custom path
        target_path = tempfile.mktemp()

        self.assertFalse(os.path.isfile(target_path))
        res = render_template(tmpl_path, context=dict(abc="test1", xyz=123), target_path=target_path)
        self.assertTrue(os.path.isfile(target_path))
        # after asserting that the file was created it can be removed
        os.remove(target_path)






