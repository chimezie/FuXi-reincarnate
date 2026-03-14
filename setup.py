#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

config = dict(
    name="fuxi",
    version="1.4",
    description="An OWL / N3-based in-memory, logic reasoning system for RDF",
    author="Chime Ogbuji",
    author_email="chimezie@gmail.com",
    maintainer="RDFLib Team",
    maintainer_email="rdflib-dev@google.com",
    platforms=["any"],
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: BSD License",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Operating System :: OS Independent",
        "Natural Language :: English",
    ],
    package_dir={
        "fuxi": "lib",
    },
    packages=[
        "fuxi",
        "fuxi.LP",
        "fuxi.SPARQL",
        "fuxi.Rete",
        "fuxi.DLP",
        "fuxi.Horn",
        "fuxi.Syntax",
    ],
    install_requires=["rdflib>2"],
    license="Apache",
    keywords="python logic owl rdf dlp n3 rule reasoner",
    url="https://github.com/RDFLib/FuXi",
    entry_points={
        "console_scripts": [
            "fuxi = fuxi.Rete.CommandLine:main",
        ],
    },
    zip_safe=False,
)

setup(**config)
