# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#

import os
import sys
from datetime import date
from importlib.metadata import version


# -- Project information -----------------------------------------------------

project = 'MxDC'
copyright = '2006-{}, Canadian Light Source, Inc'.format(date.today().year)
author = 'Michel Fodje'

# The full version, including alpha/beta/rc tags
release = version('mxdc')
version = '.'.join(release.split('.')[:2])


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
     'sphinx.ext.autodoc',
     'sphinx.ext.autosummary',
     'sphinx.ext.intersphinx',
     'sphinx.ext.napoleon'
]

# intersphinx_mapping = {
#      'gtk': ('https://lazka.github.io/pgi-docs/Gtk-3.0', None),
#      'gobject': ('https://lazka.github.io/pgi-docs/GObject-2.0', None),
#      'glib': ('https://lazka.github.io/pgi-docs/GLib-2.0', None),
#      'gdk': ('https://lazka.github.io/pgi-docs/Gdk-3.0', None),
#      'gio': ('https://lazka.github.io/pgi-docs/Gio-2.0', None),
#      'python': ('https://docs.python.org/3', None),
# }

# Add any paths that contain templates here, relative to this directory.
templates_path = []

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_show_sourcelink = False
html_theme = 'sphinx_rtd_theme'
html_show_sphinx = False

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['static']
html_style = 'css/styles.css'

napoleon_custom_sections = ['signals', 'properties', 'attributes']
