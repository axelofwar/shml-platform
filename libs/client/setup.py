"""
SHML Client SDK setup configuration.
"""

from setuptools import setup, find_packages

setup(
    name="shml-client",
    version="0.1.0",
    description="Python client for SHML Platform Ray Compute API",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="axelofwar",
    author_email="platform@shml.dev",
    url="https://github.com/axelofwar/shml-platform",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "httpx>=0.24.0",
        "pydantic>=2.0.0",
        "click>=8.0.0",  # For CLI
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "shml=shml.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    keywords="ml machine-learning ray gpu compute api client",
)
