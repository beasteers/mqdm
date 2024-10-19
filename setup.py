import setuptools

setuptools.setup(
    name='mqdm',
    version='1.0.0',
    description='',
    long_description=open('README.md').read().strip(),
    long_description_content_type='text/markdown',
    packages=setuptools.find_packages(),
    install_requires=[
        'rich', 
        'pdbr', 'fire'  # not strictly necessary
    ],
    extras_require={
    })