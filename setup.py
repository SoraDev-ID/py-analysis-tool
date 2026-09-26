from setuptools import setup, find_packages

setup(
    name="py-analysis-tool",
    version="1.0.0",
    description="Educational toolkit for inspecting Python bytecode and packaged applications",
    author="SoraDev-ID",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "xdis>=6.1.0",
        "tqdm>=4.66.0",
        "colorama>=0.4.6",
        "requests>=2.31.0",
    ],
    extras_require={
        "legacy": [
            "uncompyle6>=3.9.0",
            "decompyle3>=3.9.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "py-analysis=py_analysis_tool.main:main",
        ],
    },
)