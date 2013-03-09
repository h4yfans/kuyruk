from setuptools import setup

setup(
    name='kuyruk',
    version='0.1',
    packages=['kuyruk'],
    install_requires=['pika>=0.9.9'],
    entry_points = {
        'console_scripts': [
            'kuyruk = kuyruk:main',
        ],
    }
)