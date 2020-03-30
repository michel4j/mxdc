import sys, os, subprocess

from sphinx.highlighting import lexers
from pygments.lexers.web import PhpLexer


project = u'MxDC'
copyright = u'2006-20, Canadian Light Source, Inc'
master_doc = 'index'
templates_path = ['_templates']
extensions = []
source_suffix = '.rst'
version = subprocess.check_output(['git', 'describe'])

exclude_patterns = ['_build', '___junk.docs-src']

# -- HTML theme settings ------------------------------------------------

html_show_sourcelink = True
html_sidebars = {
    '**': [
        'logo-text.html',
        'globaltoc.html',
        'searchbox.html',
    ],
}

import guzzle_sphinx_theme

extensions.append("guzzle_sphinx_theme")
html_theme_path = guzzle_sphinx_theme.html_theme_path()
html_theme = 'guzzle_sphinx_theme'

# Guzzle theme options (see theme.conf for more information)
html_theme_options = {
    "base_url": "http://my-site.com/docs-src/"
}
