from setuptools import setup, find_packages
from mxdc.version import get_version

with open("README.md", "r") as fh:
    long_description = fh.read()

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='mxdc',
    version=get_version(),
    url="https://github.com/michel4j/mxdc",
    license='MIT',
    author='Michel Fodje',
    author_email='michel4j@gmail.com',
    description='Mx Data Collector',
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords='beamline data-acquisition crystallography MX',
    include_package_data=True,
    packages=find_packages(),
    package_data={
        'mxdc': [
            'share/data/simulated/*.raw',
            'share/data/*.*',
            'share/gtk/*.*',
            'share/gschemas.compiled',
            'share/mxdc.*.xml',
            'share/mxdc.gresource',
            'share/styles.less'
        ]
    },
    install_requires=requirements,
    scripts=[
        'bin/archiver',
        'bin/blconsole',
        'bin/hutchviewer',
        'bin/imgview',
        'bin/mxdc',
        'bin/plotxdi',
        'bin/sim-console',
        'bin/sim-mxdc'
    ],
    classifiers=[
        'Intended Audience :: Developers',
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
