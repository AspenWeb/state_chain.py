from os.path import dirname, join
from setuptools import setup


setup(
    name='state_chain',
    author='Chad Whitacre et al.',
    author_email='team@aspen.io',
    description="Model algorithms as a list of functions operating on a shared state object.",
    long_description=open(join(dirname(__file__), 'README.rst')).read(),
    long_description_content_type='text/x-rst',
    url='https://state-chain-py.readthedocs.io/',
    version='1.5.0.dev0',
    py_modules=['state_chain'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
