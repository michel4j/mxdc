from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='mxdc',
    version='2020.4.1',
    url="https://github.com/michel4j/mxdc",
    license='MIT',
    author='Michel Fodje',
    author_email='michel4j@gmail.com',
    description='Mx Data Collector',
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords='beamline data-acquisition crystallography MX',
    packages=['distutils', 'distutils.command'],
    install_requires=['gepics'],
    scripts=['scripts/xmlproc_parse', 'scripts/xmlproc_val'],
    classifiers=[
        'Intended Audience :: Developers',
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
