import argparse
from . import core
from ipydex import IPS, activate_ips_on_exception

activate_ips_on_exception()

"""
This file contains the script entry point for the `deploymentutils` command line utility 
"""


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "--remove-secrets-from-config",
        help="Creates a new `...-example.ini` file where every "
        "variable ending in `_pass` or `_key` is filled with a dummy-value",
        metavar="path_to_config",
    )

    args = argparser.parse_args()

    if args.remove_secrets_from_config:
        core.remove_secrets_from_config(args.remove_secrets_from_config)

    else:
        print("This is the deploymentutils command line tool\n")
        argparser.print_help()

    print(core.bgreen("done"))
