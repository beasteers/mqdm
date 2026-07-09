import setuptools

setuptools.setup(
    name='mqdm',
    version='2.0.0',
    description='cross-process progress bars',
    long_description=open('README.md').read().strip(),
    long_description_content_type='text/markdown',
    packages=setuptools.find_packages(),
    python_requires='>=3.10',
    install_requires=[
        'rich>=13'
    ],
    extras_require={
        'test': [
            'pytest',
            'fire'
        ],
        'dev': [
            'fire',
            'ipython',
            'pyinstrument',
            'pdbr'
        ],
        'docs': [
            'mkdocs',
            'mkdocs-material',
            'mkdocstrings[python]',
            'pymdown-extensions',
            'ruff',
        ]
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Environment :: Console',
        'Topic :: Software Development :: Libraries',
        'Topic :: Utilities',
    ],
)
