from setuptools import setup, find_packages

with open("README.rst", "r") as fh:
    long_description = fh.read()

with open('requirements.txt') as f:
    requirements = f.read().splitlines()


def my_version():
    from setuptools_scm.version import get_local_dirty_tag

    def clean_scheme(version):
        return get_local_dirty_tag(version) if version.dirty else ''

    def version_scheme(version):
        return str(version.format_with('{tag}.{distance}'))

    return {'local_scheme': clean_scheme, 'version_scheme': version_scheme}


setup(
    name='mxdc',
    use_scm_version=my_version,
    url="https://github.com/michel4j/mxdc",
    license='MIT',
    author='Michel Fodje',
    author_email='michel4j@gmail.com',
    description='Mx Data Collector',
    long_description=long_description,
    long_description_content_type="text/x-rst",
    keywords='beamline data-acquisition crystallography MX',
    include_package_data=True,
    packages=find_packages(),
    package_data={
        'mxdc': [
            'share/data/simulated/*.*',
            'share/data/*.*',
            'share/gschemas.compiled',
            'share/mxdc.*.xml',
            'share/mxdc.gresource',
            'share/styles.css',
            'share/dark.mplstyle',
            'share/imgsync.tac',
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
        'bin/sim-mxdc',
    ],
    classifiers=[
        'Intended Audience :: Developers',
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
