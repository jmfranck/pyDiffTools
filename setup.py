from setuptools import setup

setup(
    name='pyDiffTools',
    version='0.1.4',
    author="J M Franck",
    packages=['pydifftools',],
    license=open('LICENSE.md').read(),
    long_description=open('README.rst').read(),
    package_data={'pyDiffTools':['diff-doc.js','xml2xlsx.vbs']},
    entry_points=dict(
        console_scripts=["pydifft = pydifftools.command_line:main",])
)
