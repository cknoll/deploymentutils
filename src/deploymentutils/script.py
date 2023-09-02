import argparse
from . import core
from . import release
from ipydex import IPS, activate_ips_on_exception

activate_ips_on_exception()

"""
This file contains the script entry point for the `deploymentutils` command line utility
"""


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "-rs",
        "--remove-secrets-from-config",
        help="Creates a new `...-example.ini` file where every "
        "variable name containing 'pass', 'key' or 'secret' is filled with a dummy-value",
        metavar="path_to_config",

    )
    argparser.add_argument(
        "--output", "-o", help="optional output file", default=None
    )

    argparser.add_argument("--version", help="print version and exit", action='store_true')

    args = argparser.parse_args()

    if args.version:
        print(release.__version__)
        exit()
    if args.remove_secrets_from_config:
        core.remove_secrets_from_config(args.remove_secrets_from_config, new_path=args.output)

    else:
        print("This is the deploymentutils command line tool\n")
        argparser.print_help()

    print(core.bgreen("done"))
