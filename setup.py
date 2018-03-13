#!/usr/bin/env python
import os
from setuptools import setup


setup(
    name='wafe',
    description='Waveform feature extractor',
    version='0.1',
    author='Simone Cesca, Sebastian Heimann',
    author_email='simone.cesca@gfz-potsdam.de',
    packages=[
        'wafe',
        'wafe.apps',
    ],
    entry_points={
        'console_scripts': [
            'wafe = wafe.apps.__main__:main',
        ]
    },
    package_dir={'wafe': 'src'},
    data_files=[],
    )
