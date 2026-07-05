from setuptools import setup, find_packages

setup(
    name="fourtindex",
    version="0.1.0",
    description="Local Codebase Indexer & MCP Assistant",
    author="trung",
    py_modules=["main"],
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "chromadb>=0.4.24",
        "ollama>=0.2.1",
        "mcp>=1.0.0",
        "pyyaml>=6.0.1",
        "rich>=13.7.1",
    ],
    entry_points={
        "console_scripts": [
            "fourtindex=main:main",
        ],
    },
    python_requires=">=3.10",
)
