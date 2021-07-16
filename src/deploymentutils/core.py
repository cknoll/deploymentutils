import os
from typing import List, Union
from typing_extensions import Literal  # for py3.7 support
import inspect
import subprocess
import argparse
import datetime
import time
import requests
from fabric import Connection
from paramiko.ssh_exception import PasswordRequiredException
from invoke import UnexpectedExit
from jinja2 import Environment, FileSystemLoader
from colorama import Style, Fore
from ipydex import IPS


class Container(object):
    def __init__(self, **kwargs):
        self.__dict__.update(**kwargs)


class EContainer(Container):
    def __init__(self, **kwargs):
        self.exited = None
        self.stdout = ""
        self.stderr = ""
        super().__init__(**kwargs)


# it is useful for deployment scripts to handle cli arguments
# the following reduces the boilerplate
argparser = argparse.ArgumentParser()
argparser.add_argument("target", help="deployment target: `local` or `remote`.", choices=["local", "remote"])
argparser.add_argument("-u", "--unsafe", help="omit security confirmation", action="store_true")
argparser.add_argument("-i", "--initial", help="flag for initial deployment", action="store_true")
argparser.add_argument(
    "-l", "--symlink", help="use symlinking instead of copying (local deployment only)", action="store_true"
)


def parse_args(*args, **kwargs):
    args = argparser.parse_args(*args, **kwargs)
    if args.target != "local" and args.symlink:
        raise ValueError(f"incompatible options: target: {args.target} and --symlink: True")
    return args


def render_template(tmpl_path, context, target_path=None):
    """
    Render a jinja2 template and save it to target_path. If target_path ist `None` (default),
    autogenerate it by dropping the then mandatory `template_` substring of the templates filename.

    :param tmpl_path:
    :param context:     dict with context data for rendering
    :param target_path: None or string
    :return:
    """

    path, fname = os.path.split(tmpl_path)
    assert path != ""

    jin_env = Environment(loader=FileSystemLoader(path))

    if target_path is None:
        special_str = "template_"
        assert fname.startswith(special_str) and (fname.count(special_str) == 1) and len(fname) > len(special_str)
        res_fname = fname.replace(special_str, "")
        target_path = os.path.join(path, res_fname)

    template = jin_env.get_template(fname)
    if "warning" not in context:
        context["warning"] = "This file was autogenerated from the template: {}".format(fname)
    result = template.render(context=context)

    with open(target_path, "w") as resfile:
        resfile.write(result)

    # also return the result (useful for testing)
    return result


class StateConnection(object):
    """
    Wrapper class for fabric connection which remembers the working directory. Also has a target attribute to
    distinquis between remote and local operation.
    """

    def __init__(self, remote, user, target="remote"):
        self.dir = None
        self.cwd = None
        self.venv_path = None
        self.venv_target = None
        self.last_result = None
        self.last_command = None
        self.remote = remote
        self.user = user
        self.env_variables = {}

        assert target in ("remote", "local")
        self.target = target
        if target == "remote":
            self._c = Connection(remote, user)
            res = self.run('echo "Connection successful!"', hide=True)
            if res.exited != 0:
                msg = "Could not connect via ssh. Ensure that ssh-agent is activated."
                raise SystemExit(msg)
        else:
            self._c = None

    def cprint(self, txt, target_spec="both"):
        """
        Colored print-function. Color (bright or gray) depends on `target_spec` and `self.target`.

        :param txt:           the string to print
        :param target_spec:   one of `both` (default), `remote` or `local`
        :return:
        """

        if target_spec in (self.target, "both"):
            print(bright(txt))
        else:
            msg = f"Omit: (target_spec is not {self.target} "
            print(dim(f"{msg}{txt}"))

    def activate_venv(self, venv_path, venv_target: Literal["remote", "both"] = "remote"):
        """
        Store the virtual environment which should be activated for all commands (until deactivation).
        Also execute a test command.

        :param venv_path:    path to the activate script
        :param venv_target:  target platform
        """

        self.venv_path = venv_path
        self.venv_target = venv_target

        # !! this assumes to run remote
        return self.run('python -c "import sys; print(sys.path)"')

    def deactivate_venv(self):

        self.venv_path = None
        self.venv_target = None

    def chdir(self, path, target_spec: Literal["remote", "local", "both"] = "both", tolerate_error=False):
        """
        The following works on uberspace:

        c.chdir("etc")
        c.chdir("~")
        c.chdir("$HOME")

        :param path:
        :param target_spec:
        :param tolerate_error:
        :return:
        """

        if path is None:
            self.dir = None
            return

        assert len(path) > 0

        # handle relative paths

        if path[0] not in ("/", "~", "$"):
            # path is a relative directory
            if self.dir is None:
                # this should prevent too hazardous invocations
                msg = "Relative path cannot be the first path specification"
                raise ValueError(msg)

            pwd_res = self.run("pwd", hide=True, warn=True, target_spec=target_spec)
            assert pwd_res.exited == 0
            abs_path = f"{pwd_res.stdout.strip()}/{path}"
        else:
            # !! handle the cases of $RELATIVE_PATH and $UNDEFINED (however, not so important)
            abs_path = path

        old_path = self.dir
        self.dir = abs_path

        cmd = "pwd"
        res = self.run(cmd, hide=True, warn=True, target_spec=target_spec)
        pwd_txt = res.stdout.strip()

        if res.exited != 0:
            print(bred(f"Could not change directory. Error message: {res.stderr}"))
            self.dir = old_path

        # assure they have the last component in common
        # the rest might differ due to symlinks and relative paths
        elif not pwd_txt.endswith(os.path.split(path)[1]):
            if not tolerate_error and not path.startswith("~") and not path.startswith("$"):
                print(bred(f"Could not change directory. `pwd`-result: {res.stdout}"))
            self.dir = old_path
            res = EContainer(exited=1, old_res=res)

        return res

    def set_env(self, name: str, value: str):
        self.env_variables[name] = value

    def run(
        self,
        cmd,
        use_dir: bool = True,
        hide: bool = False,
        warn: Union[bool, str] = "smart",
        printonly=False,
        target_spec: Literal["remote", "local", "both"] = "remote",
        use_venv: bool = True,
    ):
        """

        :param cmd:             the command to execute, preferably as a list like it is expected by subprocess
        :param use_dir:         boolean flag whether or not to use self.dir
        :param use_venv:        boolean flag whether or not to use self.venv_path
        :param hide:            see docs of invoke {"out", "err", True, False}
        :param warn:            see docs of invoke and handling of "smart" bewlow
        :param printonly:       flag for debugging
        :param target_spec:     str; default: "remote"
        :return:
        """

        # full_command_list will be a list of lists
        if isinstance(cmd, list):
            full_command_list = [cmd]
        else:
            full_command_list = [cmd.split(" ")]

        cmd_txt = " ".join(full_command_list[-1])

        self.cwd = None  # reset possible residuals from last call
        if use_dir and self.dir is not None:
            if self.target == "remote":
                full_command_list.insert(0, ["cd", self.dir])
            else:
                self.cwd = self.dir

        assert target_spec in ("remote", "local", "both")
        assert self.venv_target in (None, "remote", "both")

        for env_var, value in self.env_variables.items():
            full_command_list.insert(0, ["export", f'{env_var}="{value}"'])

        venv_target_condition = self.venv_target == "both" or (target_spec != "local" and self.venv_target is not None)

        if use_venv and self.venv_path is not None and venv_target_condition:
            full_command_list.insert(0, ["source", self.venv_path])

        self.last_command = full_command_list

        if warn == "smart":
            # -> get a result object (which would not be the case for warn=False)
            warn = True

            # safe the result self.last_result
            smart_error_handling = True
        else:
            smart_error_handling = False

        if not hide:
            print(dim("-> "), cmd_txt)

        if not printonly:
            # noinspection PyUnusedLocal
            try:
                if not hide:
                    print(dim("<- "), end="")
                res = self.run_target_command(full_command_list, hide=hide, warn=warn, target_spec=target_spec)
            except UnexpectedExit as ex:

                if warn:
                    # fabric/invoke raises this error on "normal failure"

                    msg = (
                        f"The command {cmd} failed. You can run it again with `warn=smart` (recommendend) or"
                        f"`warn=True` and inspect `result.stderr` to get more information.\n"
                        f"Original exception follows:\n"
                    )

                    raise ValueError(msg)
                else:
                    res = EContainer(exited=1, exception=ex)

            except PasswordRequiredException as ex:
                print(bred("Could not connect via ssh. Ensure that ssh-agent is activated."))
                print(dim("hint: use something like `eval $(ssh-agent); ssh-add -t 1m`\n"))
                res = EContainer(exited=1, exception=ex)
            else:
                self.last_result = res
                if smart_error_handling and res.exited != 0:
                    msg = (
                        f"The command `{cmd}` failed with code {res.exited}. This is res.stderr:\n\n"
                        f"{res.stderr}\n\n"
                        "You can also investigate c.last_result and c.last_command"
                    )
                    raise ValueError(msg)
        else:
            # printonly mode
            res = EContainer(exited=0)

        return res

    def run_target_command(
        self, full_command_lists: List[list], hide: bool, warn: bool, target_spec: str
    ) -> Union[EContainer, subprocess.CompletedProcess]:
        """
        Actually run the command (or not), depending on self.target and target_spec.

        :param full_command_lists:  nested list of commands like: [["cd", "/path"], ["echo", "$(pwd)"]]
        :param hide:
        :param warn:
        :param target_spec:
        :return:
        """

        assert isinstance(full_command_lists, list) and isinstance(full_command_lists[0], list)

        full_command_txt = "; ".join([" ".join(cmd_list) for cmd_list in full_command_lists])

        # this is only for status messages
        last_command = " ".join(full_command_lists[-1])
        omit_message = dim(f"> Omitting command `{last_command}`\n> due to target_spec: {target_spec}.")

        assert self.target in ("local", "remote"), f"Invald target: {self.target}"
        if self.target == "remote":

            if target_spec in ("remote", "both"):
                res = self._c.run(full_command_txt, hide=hide, warn=warn)
            else:
                print(omit_message)
                res = EContainer(exited=0, command_omitted=True)
        else:
            # -> self.target != "remote"
            # TODO : handle warn flag
            if target_spec in ("local", "both"):
                orig_dir = os.getcwd()

                if self.cwd:
                    # necessatry because subprocess.run does not work with "cd my/path; mycommand"
                    os.chdir(self.cwd)

                res = None

                # use full_command_txt because of source venv
                # this loop only saves the result of the last command in res, but that is OK
                # for cmd_list in full_command_lists:
                #     # expect a CompletedProcess Instance
                #     cmd = " ".join(cmd_list) # this is necessary due to shell=True
                #     res = subprocess.run(cmd, capture_output=True, shell=True)
                #     res.exited = res.returncode
                #     res.stdout = res.stdout.decode("utf8")
                #     res.stderr = res.stderr.decode("utf8")

                res = subprocess.run(full_command_txt, capture_output=True, shell=True, executable="/bin/bash")
                res.exited = res.returncode
                res.stdout = res.stdout.decode("utf8")
                res.stderr = res.stderr.decode("utf8")

                os.chdir(orig_dir)
                if res is not None and res.stdout and hide not in (True, "out"):
                    print(res.stdout)

            else:
                # -> self.target != "remote" but target_spec == "remote"
                print(omit_message)
                res = EContainer(exited=0, command_omitted=True)

        return res

    def rsync_upload(
        self, source, dest, target_spec, filters="", printonly=False, tol_nonzero_exit=False, delete=False
    ):
        """
        Perform the appropriate rsync command (or not), depending on self.target and target_spec.

        :param source:
        :param dest:
        :param target_spec:
        :param filters:
        :param printonly:
        :param tol_nonzero_exit:    boolean; tolerate nonzero exit code
        :param delete:              insert the --delete flag
        :return:
        """

        # construct the destionation
        if self.target == "remote":
            full_dest = f"{self.user}@{self.remote}:{dest}"
        else:
            full_dest = dest

        return self._rsync_call(
            source,
            full_dest,
            target_spec,
            filters,
            printonly=printonly,
            tol_nonzero_exit=tol_nonzero_exit,
            delete=delete,
        )

    def rsync_download(
        self, source, dest, target_spec, filters="", printonly=False, tol_nonzero_exit=False, delete=False
    ):
        """
        Perform the appropriate rsync command (or not), depending on self.target and target_spec.

        :param source:
        :param dest:
        :param target_spec:
        :param filters:
        :param printonly:
        :param tol_nonzero_exit:    boolean; tolerate nonzero exit code
        :param delete:              insert the --delete flag
        :return:
        """

        # construct the source
        if self.target == "remote":
            full_source = f"{self.user}@{self.remote}:{source}"
        else:
            full_source = source

        return self._rsync_call(
            full_source,
            dest,
            target_spec,
            filters,
            printonly=printonly,
            tol_nonzero_exit=tol_nonzero_exit,
            delete=delete,
        )

    def _rsync_call(self, source, dest, target_spec, filters, printonly=False, tol_nonzero_exit=False, delete=False):

        if delete is True:
            d = " --delete"
        else:
            d = ""

        if self.target == "remote":
            cmd_start = f"rsync -pthrvz{d} --rsh='ssh  -p 22'"
        else:
            cmd_start = f"rsync -pthrvz{d}"

        cmd = f"{cmd_start} {filters} {source} {dest}"

        if printonly:
            print("->:", cmd)
            res = EContainer(exited=0)
        elif target_spec != "both" and self.target != target_spec:
            print(dim(f"> Omitting rsync command `{cmd}`\n> due to target_spec: {target_spec}."))
            res = EContainer(exited=0)
        else:
            # TODO: instead of locally calling rsync, find a more elegant (plattform-independent) way to do this
            exitcode = os.system(cmd)
            res = EContainer(exited=exitcode)

            if not tol_nonzero_exit and exitcode != 0:
                msg = "rsync failed. See error message above."
                raise ValueError(msg)
        return res

    def deploy_this_package(self, pip_command="pip"):
        """
        Deploy the current version of this package to the remote host. This is a convenience function,
        to prevent to publish too much development versions of this packate to pypi or git repo.


        :return:     None
        """

        assert self.target == "remote"

        project_main_dir = get_dir_of_this_file(upcount_dir=2)  # this is where setup.py lives (toplevel)
        assert os.path.isfile(f"{project_main_dir}/setup.py")

        package_dir = project_main_dir
        package_dir_name = os.path.split(package_dir)[1]
        package_name = os.path.split(get_dir_of_this_file())[1]

        filters = (
            f"--exclude='.git/' " f"--exclude='.idea/' " f"--exclude='*/__pycache__/*' " f"--exclude='__pycache__/' "
        )

        self.rsync_upload(package_dir, "~/tmp", filters=filters, target_spec="remote")

        self.run(f"{pip_command} uninstall -y {package_name}", warn=False)

        self.run(f"{pip_command} install ~/tmp/{package_dir_name}")


def warn_user(appname, target, unsafe_flag, deployment_path, user=None, host=None):

    user_at_host = f"{user}@{host}"
    print(
        f"\n  You are running the deployment for {bright(appname)} with target {bright(target)} "
        f"→ {bright(user_at_host)},\n"
        f"\n  deploymentpath: `{deployment_path}`.\n"
        f"\n  {yellow('Caution:')} All exisitng user data of the app and any other changes in the\n"
        f"  deployment directory will probably be be replaced by predefined data and fixtures.\n\n"
    )

    if not unsafe_flag:
        res = input("Continue (N/y)? ")
        if res.lower() != "y":
            print(bred("Aborted."))
            exit()


def get_dir_of_this_file(upcount: int = 1, upcount_dir: int = 0):
    """
    Assumes that this function is called from a script. Return the path of that script (excluding the script itself).

    :param upcount:     specifies how many frames to go back/up
    :param upcount_dir: specifies how many directories to go up (defalut: 0)
    """

    frame = inspect.currentframe()
    for i in range(upcount):
        frame = frame.f_back

    dn = os.path.dirname(os.path.abspath(inspect.getfile(frame)))

    # if specified, go upwards some additional levels
    for i in range(upcount_dir):
        dn = os.path.dirname(dn)

    return dn


def get_nearest_config(
    fname: str = "config.ini", limit: int = None, devmode: bool = False, start_dir: Union[str, None] = None
):
    """
    Look for a file `fname` in the directory of the calling file and then up the tree (up to `limit`-steps).

    Advantage over directly using `from decouple import config` the full filename can be defined explicitly.

    :param fname:       filename or absolute path
    :param limit:       How much steps to go up at maximum (default: 4, if fname is only a filename)
    :param devmode:     Flag that triggers development mode (default: False).
                        If True variables which end with "__DEVMODE" will replace variables without such appendix

    :param start_dir:   (optional) start directory

    :return:    config object from decoupl module
    """
    assert fname.endswith(".ini")

    path0, fname = os.path.split(fname)

    if path0 != "":
        assert start_dir is None
        assert limit is None
        path0 = os.path.abspath(path0)
        limit = 0
    elif limit is None:
        limit = 4  # set the default value if fname was only a filename

    old_dir = os.getcwd()

    if start_dir is None:
        if path0 == "":
            start_dir = get_dir_of_this_file(upcount=2)
        else:
            start_dir = path0
    else:
        assert os.path.isdir(start_dir)
    os.chdir(start_dir)

    path_list = [fname]
    for i in range(limit + 1):
        path = os.path.join(*path_list)
        if os.path.isfile(path):
            break
        path_list.insert(0, "..")
    else:
        msg = f"Could not find {fname} in current directory nor in {limit} parent dirs."
        raise FileNotFoundError(msg)
    from decouple import Config, RepositoryIni, Csv

    config = Config(RepositoryIni(path))

    if devmode:
        relevant_dict = config.repository.parser.__dict__["_sections"]["settings"]
        for key, value in relevant_dict.items():
            # it seems that keys are converted to lowercase automatically
            if key.endswith("__devmode"):

                # use the value specified for the development-mode for the actual variable (if it exists)
                main_key = key.replace("__devmode", "")
                if main_key in relevant_dict:
                    relevant_dict[main_key] = value

    # enable convenient access to Csv parser and actual path of the file
    config.Csv = Csv
    config.path = os.path.abspath(path)

    os.chdir(old_dir)
    return config


def set_repo_tag(ref_path: str = None, message: str = None, repo_path: str = None, ask=True) -> None:
    """
    Set a git tag to the current or specified repo (default: `deploy/<datetime>`)

    :param ref_path:    name of the tag; default: `deploy/<datetime>`
    :param message:     message, optional
    :param ask:         flag whether to ask before tagging
    :param repo_path:   path to repository (optional); if not provided take the parent dir of the calling script

    :return:
    """

    try:
        from git import Repo, InvalidGitRepositoryError
    except ImportError:
        err_msg = "Could not import `git`-package. Omit tagging."
        print(yellow(err_msg))
        return None

    if ask:
        res = input("\n should a new tag be created for the git repo (y/N)? ")

        if res.lower().strip() != "y":
            return

    if repo_path is None:
        # assume that this function is called from a deployment script which lives in repo_root/subdir/deploy.py
        repo_path = get_dir_of_this_file(upcount=2, upcount_dir=0)

    repo_path = os.path.abspath(repo_path)
    assert os.path.isdir(repo_path)

    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        err_msg = "Could not find git repository. Omit tagging."
        print(yellow(err_msg))
        return None

    if ref_path is None:
        now = time.strftime("%Y-%m-%d__%H-%M-%S") + f"_{os.environ['TZ']}"

        ref_path = f"deploy/{now}"

    if repo.is_dirty():
        repo.git.commit("-a", "-m", "autocommit during deployment")
    repo.create_tag(ref_path, message)

    print(f"Created tag for repo: `{ref_path}`.")


def ensure_http_response(url, expected_status_code=200, sleep=0):

    assert float(sleep) == sleep and sleep >= 0, f"invalid value for sleep: {sleep}"

    time.sleep(sleep)
    try:
        r = requests.get(url)
    except requests.exceptions.SSLError as err:
        print(bred(f"{url}: There was an SSLError (see below)"))
        print(err)
        return 1

    if r.status_code == expected_status_code:
        print(bgreen(f"{url}: expected status code received: {expected_status_code}."))
        return 0
    else:
        print(bred(f"{url}: unexpected status code: {r.status_code}."))
        return 2


def dim(txt):
    return f"{Fore.LIGHTBLACK_EX}{txt}{Fore.RESET}"
    # original solution (seems not to work everywhere)
    # return f"{Style.DIM}{txt}{Style.RESET_ALL}"


def bright(txt):
    return f"{Style.BRIGHT}{txt}{Style.RESET_ALL}"


def bgreen(txt):
    return f"{Fore.GREEN}{Style.BRIGHT}{txt}{Style.RESET_ALL}"


def bred(txt):
    return f"{Fore.RED}{Style.BRIGHT}{txt}{Style.RESET_ALL}"


def yellow(txt):
    return f"{Fore.YELLOW}{txt}{Style.RESET_ALL}"
