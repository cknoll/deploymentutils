import sys
import os
from setuptools import setup, find_packages

packagename = "deploymentutils"

# consider the path of `setup.py` as root directory:
PROJECTROOT = os.path.dirname(sys.argv[0]) or "."
release_path = os.path.join(PROJECTROOT, "src", packagename, "release.py")
with open(release_path, encoding="utf8") as release_file:
    __version__ = release_file.read().split('__version__ = "', 1)[1].split('"', 1)[0]


with open("README.md", encoding="utf-8") as readme_file:
    readme = readme_file.read()


with open("requirements.txt") as requirements_file:
    requirements = requirements_file.read()


setup(
    name=packagename,
    author="Carsten Knoll",
    author_email="carsten.knoll@posteo.de",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
    ],
    description="Small python package to facilitate deployment of some personal projects.",
    install_requires=requirements,
    license="GNU General Public License v3",
    long_description=readme + "\n\n",
    long_description_content_type="text/markdown",
    include_package_data=True,
    keywords="ssh, remote execution",
    packages=find_packages("src"),
    package_dir={"": "src"},
    version=__version__,
    entry_points={"console_scripts": ["deploymentutils=deploymentutils.script:main"]},
)
