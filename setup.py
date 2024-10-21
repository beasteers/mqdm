import setuptools

setuptools.setup(
    name='mqdm',
    version='1.1.0',
    description='cross-process progress bars',
    long_description=open('README.md').read().strip(),
    long_description_content_type='text/markdown',
    packages=setuptools.find_packages(),
    install_requires=[
        'rich', 'pdbr'
    ],
    extras_require={
        'test': [
            'fire'
        ]
    })