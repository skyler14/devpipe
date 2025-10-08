"""
devpipe - Interactive browser monitoring and debugging toolkit
"""
from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="devpipe",
    version="0.1.0",
    author="Skyler Saleebyan",
    author_email="skylerbsaleebyan@gmail.com",
    description="Interactive website monitoring and debugging toolkit for CDP-based browsers",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/skyler14/devpipe",
    # Treat current directory as the devpipe package
    packages=['devpipe'],
    package_dir={'devpipe': '.'},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Topic :: Software Development :: Debuggers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.8",
    install_requires=[
        "playwright>=1.40.0",
        "requests>=2.31.0",
        "deepdiff>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "devpipe=devpipe.cli:main",
        ],
    },
)
