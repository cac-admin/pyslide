# -*- coding: utf-8 -*-
import os, sys, pdb
from setuptools import setup, find_packages

PKG_NAME = "pyslide"
VERSION = "0.5.0"
DESCRIPTION = "Python whole slide image analysis toolkit"
HOMEPAGE = "https://github.com/PingjunChen/pyslide"
LICENSE = "MIT"
AUTHOR_NAME = "Pingjun Chen"
AUTHOR_EMAIL = "pingjunchen@ieee.org"

REQS = ""
with open('requirements.txt') as f:
    REQS = f.read().splitlines()

CLASSIFIERS = [
    'Development Status :: 1 - Planning',
    'Intended Audience :: Developers',
    'Intended Audience :: Healthcare Industry',
    'Intended Audience :: Science/Research',
    'License :: OSI Approved :: MIT License',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.8',
    'Topic :: Scientific/Engineering',
]

args = dict(
    name=PKG_NAME,
    version=VERSION,
    description=DESCRIPTION,
    url=HOMEPAGE,
    license=LICENSE,
    author=AUTHOR_NAME,
    author_email=AUTHOR_EMAIL,
    packages=find_packages(),
    install_requires=REQS,
    extras_require={
        # Remote annotation is opt-in: it only needs an HTTP client, so it
        # stays out of the base install.
        "remote": ["requests>=2.25.0", "tqdm>=4.60.0"],
    },
    entry_points={
        "console_scripts": [
            "pyslide-remote=pyslide.remote.cli:main",
        ],
    },
    classifiers= CLASSIFIERS,
)

setup(**args)
