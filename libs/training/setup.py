"""Setup script for SHML Training Library."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="shml-training",
    version="0.1.0",
    author="SHML Platform Team",
    description="A modular, SOTA-optimized training framework for GPU workloads",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/shml-platform",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.9",
    install_requires=[
        "torch>=2.0",
    ],
    extras_require={
        "distributed": [
            "deepspeed>=0.10",
            "fairscale>=0.4",
        ],
        "ray": [
            "ray[default,train]>=2.0",
        ],
        "notifications": [
            "requests>=2.25",
        ],
        "all": [
            "deepspeed>=0.10",
            "fairscale>=0.4",
            "ray[default,train]>=2.0",
            "requests>=2.25",
        ],
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "black>=23.0",
            "isort>=5.0",
            "mypy>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "shml-train=shml_training.cli:main",
        ],
    },
)
