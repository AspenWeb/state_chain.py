from __future__ import absolute_import, division, print_function, unicode_literals

from setuptools import setup


setup( name='algorithm'
     , author='Gittip, LLC'
     , author_email='support@gittip.com'
     , description="Model an algorithm as a list of functions."
     , url='http://algorithm-py.readthedocs.org'
     , version='1.0.0rc1'
     , py_modules=['algorithm']
     , install_requires=['dependency_injection']
     , classifiers=[ 'Development Status :: 5 - Production/Stable'
                   , 'Intended Audience :: Developers'
                   , 'License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication'
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
