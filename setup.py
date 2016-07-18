from __future__ import absolute_import, division, print_function, unicode_literals

from setuptools import setup


setup( name='algorithm'
     , author='Chad Whitacre et al.'
     , author_email='team@aspen.io'
     , description="Model an algorithm as a list of functions."
     , url='http://algorithm-py.readthedocs.org/'
     , version='1.1.0'
     , py_modules=['algorithm']
     , install_requires=['dependency_injection']
     , classifiers=[ 'Development Status :: 5 - Production/Stable'
                   , 'Intended Audience :: Developers'
                   , 'License :: OSI Approved :: MIT License'
                   , 'Operating System :: OS Independent'
                   , 'Programming Language :: Python :: 2'
                   , 'Programming Language :: Python :: 2.6'
                   , 'Programming Language :: Python :: 2.7'
                   , 'Programming Language :: Python :: 3'
                   , 'Programming Language :: Python :: 3.2'
                   , 'Programming Language :: Python :: 3.3'
                   , 'Topic :: Software Development :: Libraries :: Python Modules'
                    ]
      )
