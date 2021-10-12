import unittest
import os
import shutil
from contextlib import contextmanager
import sys
from io import StringIO
import decouple
import tempfile
import json

import deploymentutils as du
from deploymentutils import render_template, StateConnection, get_dir_of_this_file

# noinspection PyUnresolvedReferences
from ipydex import IPS

"""
These tests only cover a fraction of the actual features. Some tests require access to a remote machine.


run tests locally with:
`export NOREMOTE=True; python -m unittest`
or
`export NOREMOTE=True; rednose`
"""

DIR_OF_THIS_FILE = os.path.dirname(os.path.abspath(sys.modules.get(__name__).__file__))

TEMPLATEDIR = os.path.join(DIR_OF_THIS_FILE, "_test_templates")
TESTDATADIR = os.path.join(DIR_OF_THIS_FILE, "_test_data")
TESTJSONDATADIR = os.path.join(DIR_OF_THIS_FILE, "_test_json_data")


class NoRemote(Exception):
    pass


# because uberspace offers many pip_commands:
pipc = "pip3.8"

args = sys.argv[1:]
sys.argv = sys.argv[0:1]

# remote_secrets.ini is obviously not included in this package
try:

    if "--no-remote" in args or os.getenv("NOREMOTE", "False").lower() == "true":
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

        expected_path = "test"
        self.assertTrue(test_path.endswith(expected_path))

    def test_render_remplate(self):
        tmpl_path = os.path.join(TEMPLATEDIR, "template_1.txt")

        # test creation of target file next to the template
        target_path = os.path.join(TEMPLATEDIR, "1.txt")
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
        res = render_template(
            tmpl_path, context=dict(abc="test1", xyz=123), target_path=target_path
        )
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

        self.assertRaises(
            (FileNotFoundError, ValueError), c.run, "nonsense_command_xyz", target_spec="local"
        )

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
            res = c.run("python3 -c \"print('123-test-789')\"", target_spec="local", hide=True)

        self.assertEqual(out.getvalue().strip(), "")
        self.assertTrue("123-test-789" in res.stdout)

    def test_run_command_with_env_var(self):
        c = StateConnection(remote=None, user=None, target="local")

        c.set_env("TEST_ENV_VAR", "ABC-XYZ")
        res = c.run("echo $TEST_ENV_VAR", target_spec="local")
        self.assertIn("ABC-XYZ", res.stdout)

    def test_rsync_upload(self):

        c = StateConnection(remote=None, user=None, target="local")
        target_path = os.path.abspath(os.path.join(os.getenv("HOME"), "tmp", "du_rsync_test"))
        c.run(f"rm -rf {target_path}", target_spec="both")
        c.run(f"mkdir -p {target_path}", target_spec="both")

        src1 = os.path.join(TESTDATADIR, "data1", "dir")
        src2 = os.path.join(TESTDATADIR, "data2", "dir")
        src3 = os.path.join(TESTDATADIR, "data3", "dir")
        res = c.rsync_upload(src1, dest=target_path, target_spec="both")

        self.assertEqual(res.exited, 0)

        expected_structure = [
            (f"{target_path}", ["dir"], []),
            (f"{target_path}/dir", [], ["file1.txt"]),
        ]

        real_structure = sorted_walk_lists(target_path)
        self.assertEqual(expected_structure, real_structure)

        res = c.rsync_upload(src2, dest=target_path, target_spec="both")
        expected_structure = [
            (f"{target_path}", ["dir"], []),
            (f"{target_path}/dir", ["subdir"], ["file1.txt", "file2.txt"]),
            (f"{target_path}/dir/subdir", [], ["file3.txt"]),
        ]
        real_structure = sorted_walk_lists(target_path)
        self.assertEqual(expected_structure, real_structure)

        res = c.rsync_upload(src3, dest=target_path, delete=True, target_spec="both")
        expected_structure = [
            (f"{target_path}", ["dir"], []),
            (f"{target_path}/dir", [], ["file1.txt", "file4.txt"]),
        ]
        real_structure = sorted_walk_lists(target_path)
        self.assertEqual(expected_structure, real_structure)

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
        self.assertEqual(
            config("testvalue_csv", cast=config.Csv()), ["string1", "string2", "some more words"]
        )
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
        self.assertRaises(
            FileNotFoundError,
            du.get_nearest_config,
            fname=target_name,
            start_dir=DIR_OF_THIS_FILE,
            limit=1,
        )

        config2 = du.get_nearest_config(target_name, start_dir=DIR_OF_THIS_FILE, limit=2)
        self.assertEqual(config2("testvalue1"), "OK")
        os.remove(target_path)

        abspath = "/does/not/exist.ini"

        self.assertRaises(FileNotFoundError, du.get_nearest_config, fname=abspath, start_dir=None)

        abspath = os.path.join(DIR_OF_THIS_FILE, "test_config.ini")
        config3 = du.get_nearest_config(abspath)
        self.assertEqual(config3("testvalue1"), "OK")

    def test_render_json(self):

        data_path = os.path.join(TESTJSONDATADIR, "data1.json")
        target_path = tempfile.mktemp()

        new_data = {"key2": {"abc": 1234, "xyz": "new value"}, "key3": 100}

        du.render_json_template(data_path, new_data, target_path)

        self.assertTrue(os.path.isfile(target_path))
        with open(target_path) as jsonfile:
            res = json.load(jsonfile)

        # test merge (persistence of old data)
        self.assertEqual(res["key1"]["lore"], "foo")
        self.assertEqual(res["key2"]["stable_key"], "baz")

        # test new data
        self.assertEqual(res["key2"]["xyz"], "new value")  # old key new value
        self.assertEqual(res["key2"]["abc"], 1234)  # new key
        self.assertEqual(res["key3"], 100)  # new top level key
        os.remove(target_path)

        # do the same with yaml source file
        data_path = os.path.join(TESTJSONDATADIR, "data2.yml")

        du.render_json_template(data_path, new_data, target_path)

        self.assertTrue(os.path.isfile(target_path))
        with open(target_path) as jsonfile:
            res = json.load(jsonfile)

        self.assertEqual(res["type"], "YAML")

        # test merge (persistence of old data)
        self.assertEqual(res["key1"]["lore"], "foo")
        self.assertEqual(res["key2"]["stable_key"], "baz")

        # test new data
        self.assertEqual(res["key2"]["xyz"], "new value")  # old key new value
        self.assertEqual(res["key2"]["abc"], 1234)  # new key
        self.assertEqual(res["key3"], 100)  # new top level key
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
        res = self.c.run(f"pip install --upgrade pip setuptools", warn=False)

        # this is expexted to fail
        res = self.c.run(f"pip show deploymentutils", warn=False)
        self.assertNotEqual(res.exited, 0)

        self.c.deploy_this_package()

        res = self.c.run(f"pip show deploymentutils", warn=False)
        self.assertEqual(res.exited, 0)

    def test_run_command_with_env_var(self):

        self.c.set_env("TEST_ENV_VAR", "ABC-XYZ")
        res = self.c.run("echo $TEST_ENV_VAR", target_spec="both")
        self.assertIn("ABC-XYZ", res.stdout)


# ######################################################################################################################

#                                  helper functions for tests

# ######################################################################################################################


def sorted_walk_lists(target_path):
    """Helper function to ensure reproducible result of os.walk()"""

    top_list = list(os.walk(target_path))
    for tup in top_list:
        t1, t2, t3 = tup
        assert isinstance(t1, str)
        assert isinstance(t2, list)
        assert isinstance(t3, list)

        t2.sort()
        t3.sort()

    return top_list


if __name__ == "__main__":
    if __name__ == "__main__":
        unittest.main()
