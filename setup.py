<<<<<<< HEAD
from distutils.core import setup

setup(
    name='pyDiffTools',
    version='0.1dev',
    packages=['pydifftools',],
    license=open('LICENSE.md').read(),
    long_description=open('README.rst').read(),
=======
from setuptools import setup

setup(
    name='pyDiffTools',
    version='0.1.2',
    author="J M Franck",
    packages=['pydifftools',],
    license=open('LICENSE.md').read(),
    long_description=open('README.rst').read(),
    entry_points=dict(
        console_scripts=["pydifft = pydifftools.command_line:main",])
>>>>>>> c600fae83b1e7911c76be995619e6ea1e45fe5a0
)
