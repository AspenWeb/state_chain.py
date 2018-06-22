from __future__ import absolute_import, division, print_function, unicode_literals

from setuptools import setup


setup( name='state_chain'
     , author='Chad Whitacre et al.'
     , author_email='team@aspen.io'
     , description="Model algorithms as a list of functions operating on a shared state dict."
     , url='https://state-chain-py.readthedocs.io/'
     , version='1.3.0'
     , py_modules=['state_chain']
     , install_requires=['dependency_injection >= 1.2.0']
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
