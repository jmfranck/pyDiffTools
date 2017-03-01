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
)

print "WARNING js and vbs currently expected in the home directory -- modify so they are installed with the package"
