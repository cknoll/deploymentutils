import unittest
import os
import shutil
import json
import tempfile
from contextlib import contextmanager
import sys
from io import StringIO
import decouple

import deploymentutils as du
from deploymentutils import render_template, StateConnection, get_dir_of_this_file

# noinspection PyUnresolvedReferences
from ipydex import IPS

"""
These tests can only cover a fraction of the actual features, because the tests do not have access to a remote machine
"""

TEMPLATEDIR = "_test_templates"

DIR_OF_THIS_FILE = os.path.dirname(os.path.abspath(sys.modules.get(__name__).__file__))

class NoRemote(Exception):
    pass

# because uberspace offers many pip_commands:
pipc = "pip3.8"

# remote_secrets.ini is obviously not included in this package
try:

    if 1 or "--no-remote" in sys.argv:
        sys.argv.remove("--no-remote")
        raise NoRemote

    remote_secrets = du.get_nearest_config("remote_secrets.ini", start_dir=DIR_OF_THIS_FILE)
    remote_server = remote_secrets("remote_server")
    remote_user = remote_secrets("remote_user")
except (FileNotFoundError, decouple.UndefinedValueError, NoRemote):
    remote_server = None
    remote_user = None


@contextmanager
def captured_output():
    """
    use out.getvalue().strip() and err.getvalue().strip()
    """
    # source: https://stackoverflow.com/a/17981937/333403
    new_out, new_err = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class TC1(unittest.TestCase):
    def setUp(self):
        pass

    def test_get_dir_of_this_file(self):
        test_path = get_dir_of_this_file()

        expected_path = os.path.join("deploymentutils", "test")
        self.assertTrue(test_path.endswith(expected_path))

    def test_render_remplate(self):
        test_path = DIR_OF_THIS_FILE
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

    def test_argparser(self):

        args = du.parse_args(["-u", "local"])

        self.assertEqual(args.target, "local")
        self.assertEqual(args.unsafe, True)

        args = du.parse_args(["local"])
        self.assertEqual(args.unsafe, False)

        with captured_output() as (out, err):
            self.assertRaises(SystemExit, du.parse_args, [])
        self.assertTrue("usage:" in err.getvalue().strip())

        with self.assertRaises(ValueError) as cm:
            du.parse_args(["-l", "remote"])
        self.assertTrue("incompatible options" in cm.exception.args[0])

    def test_run_command0(self):
        c = StateConnection(remote=None, user=None, target="local")

        self.assertRaises(FileNotFoundError, c.run, "nonsense_command_xyz", target_spec="local")

        res = c.run("pwd", target_spec="local")
        self.assertEqual(res.exited, 0)

        expected_result = os.getcwd()
        self.assertEqual(c.last_result.stdout.strip(), expected_result)

        with self.assertRaises(ValueError) as cm:
            # provoke nonzero exit code
            c.run("ls foobar_nonexistent", target_spec="local")

        self.assertTrue("foobar_nonexistent" in cm.exception.args[0])

        with captured_output() as (out, err):
            c.run("python --version", target_spec="local", hide=False)
        self.assertTrue("Python" in out.getvalue().strip())

    def test_run_command1(self):
        c = StateConnection(remote=None, user=None, target="local")

        # test if hide=True works
        with captured_output() as (out, err):
            res = c.run(['python3',  '-c', 'print("123-test-789")'], target_spec="local", hide=True)

        self.assertEqual(out.getvalue().strip(), "")
        self.assertTrue("123-test-789" in res.stdout)

    def test_get_nearest_config(self):

        # noinspection PyPep8Naming
        CONFIG_FNAME = "test_config.ini"

        # explicitly passing start_dir seems only necessary in unittests

        config = du.get_nearest_config(CONFIG_FNAME, start_dir=DIR_OF_THIS_FILE)

        self.assertEqual(config("testvalue1"), "OK")
        self.assertEqual(config("testvalue2"), "Very OK")
        self.assertEqual(config("testvalue3"), "Robust=OK")
        self.assertEqual(config("testvalue4"), '"Quoted String"')
        self.assertEqual(config("testvalue5"), "Spaces are acceptable")
        self.assertEqual(config("testvalue_number"), "1234.567")
        self.assertEqual(config("testvalue_number", cast=float), 1234.567)
        self.assertEqual(config("testvalue_csv", cast=config.Csv()), ["string1", "string2", "some more words"])
        self.assertEqual(config("testvalue_empty_str"), "")
        self.assertEqual(config("testvalue6"), "production_option")
        self.assertEqual(config("testvalue6__DEVMODE"), "development_option")
        self.assertEqual(config("testvalueX__DEVMODE"), "does not exist for production")

        self.assertRaises(decouple.UndefinedValueError, config, "testvalueX")

        config_dev = du.get_nearest_config(CONFIG_FNAME, devmode=True, start_dir=DIR_OF_THIS_FILE)
        self.assertEqual(config_dev("testvalue6"), "development_option")

        # now make a copy of the config file and place it in a parent dir

        target_name = CONFIG_FNAME.replace(".ini", "_XYZ.ini")
        target_path = os.path.join(DIR_OF_THIS_FILE, "..", "..", target_name)
        self.assertRaises(FileNotFoundError, du.get_nearest_config, fname=target_name)

        source_path = os.path.join(DIR_OF_THIS_FILE, CONFIG_FNAME)

        shutil.copy2(source_path, target_path)
        self.assertRaises(FileNotFoundError, du.get_nearest_config, fname=target_name, start_dir=DIR_OF_THIS_FILE, limit=1)

        config2 = du.get_nearest_config(target_name, start_dir=DIR_OF_THIS_FILE, limit=2)
        self.assertEqual(config2("testvalue1"), "OK")
        os.remove(target_path)


@unittest.skipUnless(remote_server is not None, "no remote server specified")
class TC2(unittest.TestCase):
    def setUp(self):
        self.c = du.StateConnection(remote_server, user=remote_user, target="remote")
        pass

    def test_remote1(self):
        res = self.c.run("hostname")
        self.assertEqual(res.exited, 0)
        self.assertEqual(remote_server, res.stdout.strip())
        self.c.chdir("~/tmp")
        res = self.c.run("pwd")
        self.assertTrue(res.stdout.strip().endswith("/tmp"))
        res = self.c.run("mkdir -p abc/xyz")
        self.c.chdir("abc/xyz")
        res = self.c.run("pwd")
        self.assertTrue(res.stdout.strip().endswith("/tmp/abc/xyz"))

        # try to access a non-existent directory
        res = self.c.chdir("ABC_XYZ", tolerate_error=True)
        self.assertNotEqual(res.exited, 0)
        self.c.chdir("~/tmp")
        res = self.c.run("rmdir -p abc/xyz")
        self.assertEqual(res.exited, 0)
        self.c.chdir("~")

    def test_venv1(self):
        self.c.chdir("~/tmp")
        res = self.c.run(f"{pipc} install --user virtualenv")

        # delete old env
        res = self.c.run(f"rm -rf test_env")
        res = self.c.run(f"virtualenv -p python3.8 test_env")
        self.c.chdir("~")
        self.c.activate_venv("~/tmp/test_env/bin/activate")
        res = self.c.run("python --version")
        self.assertTrue(res.stdout.startswith("Python 3.8"))
        res = self.c.run("python --version", use_venv=False)
        self.assertTrue(res.stderr.startswith("Python 2.7"))

        self.c.deactivate_venv()
        res = self.c.run("python --version")
        self.assertTrue(res.stderr.startswith("Python 2.7"))

        self.c.activate_venv("~/tmp/test_env/bin/activate")
        res = self.c.run("hostname", target_spec="local")
        self.assertTrue(res.command_omitted)

    def test_remote_warn(self):

        # this command returns with nonzero exit code
        res = self.c.run("pip show nonexistent_XYZ_package", warn=False)
        self.assertNotEqual(res.exited, 0)

    def test_deploy_this_package(self):

        # preparation
        self.c.chdir("~/tmp")
        res = self.c.run(f"{pipc} install --user virtualenv")
        res = self.c.run(f"rm -rf test_env")
        res = self.c.run(f"virtualenv -p python3.8 test_env")
        self.c.activate_venv("~/tmp/test_env/bin/activate")
        res = self.c.run(f'pip install --upgrade pip setuptools', warn=False)

        # this is expexted to fail
        res = self.c.run(f'pip show deploymentutils', warn=False)
        self.assertNotEqual(res.exited, 0)

        self.c.deploy_this_package()

        res = self.c.run(f'pip show deploymentutils', warn=False)
        self.assertEqual(res.exited, 0)


if __name__ == "__main__":
    if __name__ == '__main__':
        unittest.main()

